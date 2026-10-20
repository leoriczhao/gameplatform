/* 渲染 v2 · 动效参数 → 时间曲线（docs/design/16 §3.3）。
   纯函数、无副作用、无 DOM：参数一律按文档范围夹紧，非法输入返回中性值。
   - 常驻 anim：pulse / glow / bob / spin / flicker / float（period 200-5000，amount 0-1）
   - 入场 enter：pop / fade / flash / rise（ms 40-1000）
   - 事件 effect：flash / shake / pulse / dim / tint（ms 80-2000，shake amount 1-12px） */

import { clamp01, numOr } from "./paths.js";

export const ANIM_EFFECTS = ["pulse", "glow", "bob", "spin", "flicker", "float"];
export const ENTER_EFFECTS = ["pop", "fade", "flash", "rise"];
export const EVENT_EFFECTS = ["flash", "shake", "pulse", "dim", "tint"];

export const ANIM_PERIOD_MIN = 200;
export const ANIM_PERIOD_MAX = 5000;
export const ANIM_PERIOD_DEFAULT = 1000;
export const ANIM_AMOUNT_DEFAULT = 0.15;
export const ENTER_MS_MIN = 40;
export const ENTER_MS_MAX = 1000;
export const ENTER_MS_DEFAULT = 200;
export const EVENT_MS_MIN = 80;
export const EVENT_MS_MAX = 2000;
export const EVENT_MS_DEFAULT = 300;
export const SHAKE_AMOUNT_MIN = 0;
export const SHAKE_AMOUNT_MAX = 12;
export const SHAKE_AMOUNT_DEFAULT = 4;
export const TWEEN_MS = 120;

const TAU = Math.PI * 2;

/* 中性变换：不改变绘制结果。所有曲线函数都返回这一形状的超集。 */
export function neutralAnim() {
  return { scale: 1, alpha: 1, dx: 0, dy: 0, rot: 0, glow: 0 };
}

export function clampAnimPeriod(period) {
  return numOr(period, ANIM_PERIOD_DEFAULT, ANIM_PERIOD_MIN, ANIM_PERIOD_MAX);
}

export function clampAnimAmount(amount) {
  return clamp01(amount, ANIM_AMOUNT_DEFAULT);
}

export function clampEnterMs(ms) {
  return Math.round(numOr(ms, ENTER_MS_DEFAULT, ENTER_MS_MIN, ENTER_MS_MAX));
}

export function clampEventMs(ms) {
  return Math.round(numOr(ms, EVENT_MS_DEFAULT, EVENT_MS_MIN, EVENT_MS_MAX));
}

export function clampShakeAmount(amount) {
  return numOr(amount, SHAKE_AMOUNT_DEFAULT, SHAKE_AMOUNT_MIN, SHAKE_AMOUNT_MAX);
}

export function easeOutCubic(p) {
  const x = clamp01(p);
  const inv = 1 - x;
  return 1 - inv * inv * inv;
}

export function easeOutBack(p) {
  const x = clamp01(p);
  const c1 = 1.70158;
  const c3 = c1 + 1;
  const u = x - 1;
  return 1 + c3 * u * u * u + c1 * u * u;
}

export function lerp(from, to, t) {
  const a = Number.isFinite(from) ? from : 0;
  const b = Number.isFinite(to) ? to : 0;
  return a + (b - a) * clamp01(t);
}

/* 单位位置补间进度（约 120ms；instant 由调用方直接跳过）。 */
export function tweenProgress(elapsedMs, durationMs = TWEEN_MS) {
  return easeOutCubic(clamp01(numOr(elapsedMs, 0, 0, 1e9) / Math.max(1, numOr(durationMs, TWEEN_MS, 1, 1e6))));
}

/* 常驻动效：tMs 为单调时钟毫秒。dx/dy 以「格子尺寸」为单位，由渲染器换算像素。 */
export function animState(effect, tMs, period, amount) {
  const out = neutralAnim();
  const p = clampAnimPeriod(period);
  const a = clampAnimAmount(amount);
  const t = Number.isFinite(tMs) ? tMs : 0;
  const phase = TAU * (((t % p) + p) % p) / p;
  switch (effect) {
    case "pulse":
      out.scale = 1 + a * 0.5 * Math.sin(phase);
      return out;
    case "glow":
      out.glow = a * (0.5 + 0.5 * Math.sin(phase));
      return out;
    case "bob":
      out.dy = -a * 0.3 * (0.5 + 0.5 * Math.sin(phase));
      return out;
    case "spin":
      out.rot = TAU * (((t % p) + p) % p) / p;
      return out;
    case "flicker":
      out.alpha = 1 - a * (0.5 + 0.5 * Math.sin(phase));
      return out;
    case "float":
      out.dx = a * 0.25 * Math.sin(phase);
      out.dy = a * 0.2 * Math.cos(phase);
      return out;
    default:
      return out;
  }
}

/* 入场动效：返回 {scale, alpha, dy, flash, progress, done}；未知效果立即完成。 */
export function enterState(effect, elapsedMs, ms) {
  const d = clampEnterMs(ms);
  const elapsed = Number.isFinite(elapsedMs) ? Math.max(0, elapsedMs) : 0;
  const p = clamp01(elapsed / d);
  const done = p >= 1;
  const e = easeOutCubic(p);
  switch (effect) {
    case "pop":
      return { scale: 0.3 + 0.7 * easeOutBack(p), alpha: 1, dy: 0, flash: 0, progress: p, done };
    case "fade":
      return { scale: 1, alpha: e, dy: 0, flash: 0, progress: p, done };
    case "flash":
      return { scale: 1, alpha: 1, dy: 0, flash: 1 - e, progress: p, done };
    case "rise":
      return { scale: 1, alpha: e, dy: (1 - e) * 0.6, flash: 0, progress: p, done };
    default:
      return { scale: 1, alpha: 1, dy: 0, flash: 0, progress: 1, done: true };
  }
}

/* 棋盘事件效果：返回 {flash, shakeX, shakeY, scale, dim, tint, progress, done}。
   flash/dim/tint 为 0-1 叠加强度；shakeX/shakeY 为像素；scale 为整盘缩放。 */
export function eventState(kind, elapsedMs, ms, amount) {
  const d = clampEventMs(ms);
  const elapsed = Number.isFinite(elapsedMs) ? Math.max(0, elapsedMs) : 0;
  const p = clamp01(elapsed / d);
  const done = p >= 1;
  const out = {
    flash: 0, shakeX: 0, shakeY: 0, scale: 1, dim: 0, tint: 0, progress: p, done,
  };
  const decay = 1 - easeOutCubic(p);
  switch (kind) {
    case "flash":
      out.flash = decay;
      return out;
    case "shake": {
      const px = clampShakeAmount(amount);
      out.shakeX = px * decay * Math.sin(p * Math.PI * 3);
      out.shakeY = px * decay * Math.sin(p * Math.PI * 3 + 1.1);
      return out;
    }
    case "pulse":
      out.scale = 1 + numOr(amount, 0.06, 0, 1) * Math.sin(Math.PI * p);
      return out;
    case "dim":
      out.dim = numOr(amount, 0.5, 0, 1) * decay;
      return out;
    case "tint":
      out.tint = numOr(amount, 0.25, 0, 1) * decay;
      return out;
    default:
      out.progress = 1;
      out.done = true;
      return out;
  }
}

/* 合并多条同时进行的事件（加法叠加，强度夹紧 0-1）。 */
export function combineEventStates(states) {
  const out = {
    flash: 0, shakeX: 0, shakeY: 0, scale: 1, dim: 0, tint: 0, any: false, done: true,
  };
  if (!Array.isArray(states)) return out;
  for (let i = 0; i < states.length; i += 1) {
    const s = states[i];
    if (!s) continue;
    out.any = true;
    out.flash = clamp01(out.flash + s.flash);
    out.dim = clamp01(out.dim + s.dim);
    out.tint = clamp01(out.tint + s.tint);
    out.shakeX += Number.isFinite(s.shakeX) ? s.shakeX : 0;
    out.shakeY += Number.isFinite(s.shakeY) ? s.shakeY : 0;
    out.scale *= Number.isFinite(s.scale) ? s.scale : 1;
    if (!s.done) out.done = false;
  }
  return out;
}
