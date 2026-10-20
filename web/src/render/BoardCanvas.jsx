/* 渲染 v2 · canvas 2D 主渲染路径（docs/design/16 §3、§6）。
   纯声明式：只读 state + 归一化模型，不改游戏逻辑。
   性能策略：
   1) 背景 + 格子底色/描边/字形 绘制到离屏 canvas 缓存（base cache），
      签名 = 网格内容 + 占用格 + 几何/尺寸；只在变化时重建（4096 格也只重建一次）；
   2) rAF 循环只在「有常驻动效 / 入场动效 / 事件效果 / 单位补间」时运行，静止时停帧；
   3) palette 自带 anim 时放弃静态缓存（否则动效会被缓存冻结），按帧直绘。 */

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { clamp, clamp01, getPath } from "./paths.js";
import {
  TWEEN_MS, animState, combineEventStates, enterState, eventState, lerp, tweenProgress,
} from "./effects.js";
import {
  DEFAULT_CELL_BG, INK, cellAt, itemGlyphColor, ownerIndexOf, readUnitField,
  resolveDims, resolveLayerGrid, resolveUnits,
} from "./schema.js";
import { imageSize, isImageReady } from "./assets.js";

const GLYPH_RATIO = 0.45;        // v1：36px 格子 + text-base(16px) ≈ 0.45
const VECTOR_VIEWBOX = 24;       // vector.path 无 viewBox 字段，按 24×24 图标坐标系解释
const MIN_CELL_PX = 6;
const MAX_DEVICE_PX = 8e6;      // 单张 canvas（含离屏缓存）设备像素上限
const EMOJI_FONT = '"Apple Color Emoji","Segoe UI Emoji","Noto Color Emoji","Twemoji Mozilla",sans-serif';
const INK_FONT = 'ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif';

function glyphFont(sizePx) {
  return "600 " + sizePx + "px " + INK_FONT + "," + EMOJI_FONT;
}

function roundRectPath(ctx, x, y, w, h, r) {
  const radius = Math.max(0, Math.min(r, w / 2, h / 2));
  ctx.beginPath();
  if (radius <= 0.01) {
    ctx.rect(x, y, w, h);
    return;
  }
  ctx.moveTo(x + radius, y);
  ctx.lineTo(x + w - radius, y);
  ctx.arcTo(x + w, y, x + w, y + radius, radius);
  ctx.lineTo(x + w, y + h - radius);
  ctx.arcTo(x + w, y + h, x + w - radius, y + h, radius);
  ctx.lineTo(x + radius, y + h);
  ctx.arcTo(x, y + h, x, y + h - radius, radius);
  ctx.lineTo(x, y + radius);
  ctx.arcTo(x, y, x + radius, y, radius);
  ctx.closePath();
}

function cellPath(ctx, x, y, size, radius, shape) {
  if (shape === "circle") {
    ctx.beginPath();
    ctx.arc(x + size / 2, y + size / 2, Math.max(0.5, size / 2), 0, Math.PI * 2);
    return;
  }
  roundRectPath(ctx, x, y, size, size, radius);
}

function paintGlyph(ctx, text, cx, cy, sizePx, color, shadow) {
  if (typeof text !== "string" || !text.trim()) return;
  ctx.save();
  ctx.font = glyphFont(Math.max(4, Math.round(sizePx)));
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillStyle = color || INK;
  if (shadow) {
    ctx.shadowColor = "rgba(15,23,42,0.28)";
    ctx.shadowBlur = Math.max(2, sizePx * 0.18);
    ctx.shadowOffsetY = Math.max(1, sizePx * 0.08);
  }
  ctx.fillText(text, cx, cy);
  ctx.restore();
}

function paintVector(ctx, vector, cx, cy, sizePx, colorOverride) {
  let path;
  try {
    if (typeof Path2D === "undefined") return false;
    path = new Path2D(vector.path);
  } catch (err) {
    return false;
  }
  const scale = Math.max(0.01, sizePx / VECTOR_VIEWBOX);
  ctx.save();
  ctx.translate(cx, cy);
  ctx.scale(scale, scale);
  ctx.translate(-VECTOR_VIEWBOX / 2, -VECTOR_VIEWBOX / 2);
  const color = colorOverride || vector.color || INK;
  if (vector.fill !== false) {
    ctx.fillStyle = color;
    ctx.fill(path);
  } else {
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.lineJoin = "round";
    ctx.lineCap = "round";
    ctx.stroke(path);
  }
  ctx.restore();
  return true;
}

function paintSprite(ctx, img, cx, cy, box) {
  if (!img || !isImageReady(img)) return false;
  const { w, h } = imageSize(img);
  if (!w || !h) return false;
  const k = Math.min(box / w, box / h);
  ctx.drawImage(img, cx - (w * k) / 2, cy - (h * k) / 2, w * k, h * k);
  return true;
}

/* sprite → vector → glyph 的降级链（资源未就绪时自动落到 glyph）。
   size = 格子边长 × item.scale；glyph 再乘 GLYPH_RATIO 以对齐 v1 的 16px/36px。 */
function paintContent(ctx, item, cx, cy, size, colorOverride, assets, glyphFallback) {
  if (item && item.sprite && assets) {
    const img = assets.get ? assets.get(item.sprite) : null;
    if (paintSprite(ctx, img, cx, cy, size)) return true;
  }
  if (item && item.vector && paintVector(ctx, item.vector, cx, cy, size, colorOverride)) return true;
  const text = item && item.glyph ? item.glyph : glyphFallback;
  if (text) {
    paintGlyph(ctx, text, cx, cy, size * GLYPH_RATIO,
      colorOverride || itemGlyphColor(item, false), item && item.shadow);
    return true;
  }
  return false;
}

function gridSignature(grid, w, h, occupied) {
  let sig = "";
  for (let y = 0; y < h; y += 1) {
    const row = Array.isArray(grid[y]) ? grid[y] : [];
    sig += row.length > w ? row.slice(0, w).join(",") : row.join(",");
    sig += "|";
  }
  return sig + "#" + occupied;
}

export default function BoardCanvas({
  state, model, onCellClick = null, cellSize = 36, instant = false,
  interactive = false, assets = null, assetsVersion = 0,
}) {
  const wrapRef = useRef(null);
  const canvasRef = useRef(null);
  const [availWidth, setAvailWidth] = useState(0);
  const prevUnitsRef = useRef(new Map());
  const enterRef = useRef(new Map());
  const cellEnterRef = useRef(new Map());
  const prevGridRef = useRef(new Map());
  const eventsRef = useRef([]);
  const baseRef = useRef(null);
  const lastEventStateRef = useRef(null);

  /* ------------------------------------------------------------ 尺寸自适应 */
  useLayoutEffect(() => {
    const el = wrapRef.current;
    if (!el || typeof window === "undefined") return undefined;
    let raf = 0;
    const measure = () => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => {
        const own = el.clientWidth || el.getBoundingClientRect().width || 0;
        const viewport = Math.max(0, (window.innerWidth || 0) - 32);   // 页面 px-4 左右各 16px
        const next = viewport > 0 ? Math.min(own || viewport, viewport) : own;
        setAvailWidth((prev) => (Math.abs(prev - next) > 0.5 ? next : prev));
      });
    };
    measure();
    window.addEventListener("resize", measure);
    let ro = null;
    if (typeof ResizeObserver !== "undefined") {
      ro = new ResizeObserver(measure);
      ro.observe(el);
    }
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", measure);
      if (ro) ro.disconnect();
    };
  }, []);

  const dims = resolveDims(state, model);
  const w = dims.w;
  const h = dims.h;
  const gap = model.cell.gap;
  const hint = model.cell.declared
    ? model.cell.size
    : (Number.isFinite(cellSize) && cellSize > 0 ? cellSize : model.cell.size);
  let cellPx = Math.max(MIN_CELL_PX, Math.round(hint));
  if (availWidth > 0) {
    const fit = Math.floor((availWidth - (w - 1) * gap) / w);
    cellPx = clamp(Math.min(hint, fit), MIN_CELL_PX, Math.max(MIN_CELL_PX, hint));
  }
  // 设备像素面积上限：64×64 在 dpr=2 下也不会分配 >~8M 像素的 canvas / 离屏缓存
  const dprGuess = Math.max(1, Math.min(3,
    (typeof window !== "undefined" && window.devicePixelRatio) || 1));
  const areaCap = Math.floor(Math.sqrt(MAX_DEVICE_PX / (dprGuess * dprGuess * Math.max(1, w * h))));
  cellPx = Math.max(MIN_CELL_PX, Math.min(cellPx, areaCap));
  const pitch = cellPx + gap;
  const boardW = Math.max(1, w * cellPx + Math.max(0, w - 1) * gap);
  const boardH = Math.max(1, h * cellPx + Math.max(0, h - 1) * gap);

  /* --------------------------------------------------------------- 主绘制 */
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || typeof canvas.getContext !== "function") return undefined;
    let ctx = null;
    try { ctx = canvas.getContext("2d"); } catch (err) { ctx = null; }
    if (!ctx) return undefined;

    const dpr = Math.max(1, Math.min(3,
      (typeof window !== "undefined" && window.devicePixelRatio) || 1));
    const pxW = Math.max(1, Math.round(boardW * dpr));
    const pxH = Math.max(1, Math.round(boardH * dpr));
    if (canvas.width !== pxW) canvas.width = pxW;
    if (canvas.height !== pxH) canvas.height = pxH;

    let stopped = false;
    let raf = 0;
    const t0 = typeof performance !== "undefined" && performance.now ? performance.now() : Date.now();

    /* 事件队列：本帧 state.events 同帧触发一次（docs §3.5）；同一 state 对象只消费一次。 */
    const incoming = [];
    const evList = lastEventStateRef.current === state
      ? []
      : (lastEventStateRef.current = state, Array.isArray(state && state.events) ? state.events : []);
    for (let i = 0; i < evList.length && incoming.length < 32; i += 1) {
      const raw = evList[i];
      const name = typeof raw === "string" ? raw : (raw && typeof raw.name === "string" ? raw.name : "");
      if (!name) continue;
      const decl = model.events[name];
      if (!decl) continue;                       // 未声明的事件名忽略
      incoming.push({
        kind: decl.effect.kind, ms: decl.effect.ms,
        color: decl.effect.color, amount: decl.effect.amount, at: -1,
      });
    }

    const baseCanvas = () => {
      try {
        if (typeof OffscreenCanvas !== "undefined") return new OffscreenCanvas(pxW, pxH);
      } catch (err) { /* fall through */ }
      try { return document.createElement("canvas"); } catch (err) { return null; }
    };

    const buildBase = (sig, occupied, animatedCells) => {
      const cv = baseCanvas();
      if (!cv) return null;
      cv.width = pxW;
      cv.height = pxH;
      const bctx = cv.getContext("2d");
      if (!bctx) return null;
      bctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const bg = model.background;
      const transparentCells = bg.declared === true;

      if (bg.kind === "checker") {
        for (let y = 0; y < h; y += 1) {
          for (let x = 0; x < w; x += 1) {
            bctx.fillStyle = (x + y) % 2 ? bg.colors[1] : bg.colors[0];
            bctx.fillRect(x * pitch, y * pitch, cellPx, cellPx);
          }
        }
      } else if (bg.kind === "grid") {
        bctx.fillStyle = bg.colors[0];
        bctx.fillRect(0, 0, boardW, boardH);
        bctx.strokeStyle = bg.line;
        bctx.lineWidth = 1;
        for (let x = 1; x < w; x += 1) {
          bctx.beginPath();
          bctx.moveTo(x * pitch - gap / 2, 0);
          bctx.lineTo(x * pitch - gap / 2, boardH);
          bctx.stroke();
        }
        for (let y = 1; y < h; y += 1) {
          bctx.beginPath();
          bctx.moveTo(0, y * pitch - gap / 2);
          bctx.lineTo(boardW, y * pitch - gap / 2);
          bctx.stroke();
        }
      } else {
        bctx.fillStyle = bg.colors[0];
        bctx.fillRect(0, 0, boardW, boardH);
      }

      for (let y = 0; y < h; y += 1) {
        for (let x = 0; x < w; x += 1) {
          const id = cellAt(dims.grid, x, y);
          const item = model.palette[id] || null;
          const px = x * pitch;
          const py = y * pitch;
          const fill = item && item.color ? item.color : (transparentCells ? null : DEFAULT_CELL_BG);
          if (fill) {
            bctx.fillStyle = fill;
            cellPath(bctx, px, py, cellPx, model.cell.radius, model.cell.shape);
            bctx.fill();
          }
          if (model.cell.border.width > 0) {
            bctx.strokeStyle = model.cell.border.color;
            bctx.lineWidth = model.cell.border.width;
            cellPath(bctx, px + 0.5, py + 0.5, Math.max(1, cellPx - 1), model.cell.radius, model.cell.shape);
            bctx.stroke();
          }
          const key = x + "," + y;
          if (occupied.has(key) || animatedCells.has(key)) continue;
          if (item && item.bg) {
            bctx.fillStyle = item.bg;
            cellPath(bctx, px, py, cellPx, model.cell.radius, model.cell.shape);
            bctx.fill();
          }
          // v1 语义：未声明的 cell id 回退成 id 文本；已声明但无 glyph 的条目只画底色
          paintContent(bctx, item, px + cellPx / 2, py + cellPx / 2,
            cellPx * (item ? item.scale : 1),
            itemGlyphColor(item, false), assets, item ? null : id);
        }
      }
      return { canvas: cv, sig, pxW, pxH };
    };

    const drawFrame = (tMs) => {
      let animating = false;
      const units = resolveUnits(state);
      const occupied = new Set();
      units.forEach((u) => { occupied.add(Math.round(u.x) + "," + Math.round(u.y)); });

      const animatedCells = new Set();
      if (model.paletteAnimated) {
        for (let y = 0; y < h; y += 1) {
          for (let x = 0; x < w; x += 1) {
            const item = model.palette[cellAt(dims.grid, x, y)];
            if (item && item.anim) animatedCells.add(x + "," + y);
          }
        }
      }
      // 入场中的 palette 格子也要按帧重绘
      const nowEntering = [];
      if (model.hasEnter && !instant) {
        for (let y = 0; y < h; y += 1) {
          for (let x = 0; x < w; x += 1) {
            const key = x + "," + y;
            const id = cellAt(dims.grid, x, y);
            const prev = prevGridRef.current.get(key);
            if (prev !== id) {
              prevGridRef.current.set(key, id);
              const item = model.palette[id];
              if (item && item.enter) cellEnterRef.current.set(key, tMs);
            }
          }
        }
        cellEnterRef.current.forEach((start, key) => {
          const [sx, sy] = key.split(",");
          const item = model.palette[cellAt(dims.grid, Number(sx), Number(sy))];
          const decl = item && item.enter;
          if (!decl || tMs - start > decl.ms) { cellEnterRef.current.delete(key); return; }
          animatedCells.add(key);
          nowEntering.push({ x: Number(sx), y: Number(sy), item, start, decl });
        });
      }

      const sig = gridSignature(dims.grid, w, h, Array.from(occupied).sort().join(";"))
        + "@" + Array.from(animatedCells).sort().join(";")
        + "@" + (assetsVersion || 0);
      let base = baseRef.current;
      if (!base || base.sig !== sig || base.pxW !== pxW || base.pxH !== pxH) {
        base = buildBase(sig, occupied, animatedCells);
        baseRef.current = base;
      }

      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, boardW, boardH);

      // ---- 事件效果
      if (incoming.length) {
        incoming.forEach((e) => eventsRef.current.push({ ...e, at: tMs }));
        incoming.length = 0;
      }
      eventsRef.current = eventsRef.current.filter((e) => e && tMs - e.at <= e.ms + 60);
      const evStates = [];
      let evColor = null;
      eventsRef.current.forEach((e) => {
        const s = eventState(e.kind, tMs - e.at, e.ms, e.amount);
        evStates.push(s);
        if (!s.done) animating = true;
        if (e.color) evColor = e.color;
      });
      const ev = combineEventStates(evStates);

      ctx.save();
      if (ev.shakeX || ev.shakeY) ctx.translate(ev.shakeX, ev.shakeY);
      if (ev.scale !== 1) {
        const cx = boardW / 2;
        const cy = boardH / 2;
        ctx.translate(cx, cy);
        ctx.scale(ev.scale, ev.scale);
        ctx.translate(-cx, -cy);
      }

      // ---- 背景 + 静态格子（缓存）
      if (base && base.canvas) {
        ctx.drawImage(base.canvas, 0, 0, boardW, boardH);
      } else {
        ctx.fillStyle = model.background.colors[0];
        ctx.fillRect(0, 0, boardW, boardH);
      }

      // ---- 入场/动画中的 palette 格子（在缓存之上重绘）
      nowEntering.forEach((c) => {
        const es = enterState(c.decl.effect, tMs - c.start, c.decl.ms);
        const px = c.x * pitch;
        const py = c.y * pitch;
        ctx.save();
        ctx.globalAlpha = es.alpha;
        if (es.scale !== 1) {
          const cx = px + cellPx / 2;
          const cy = py + cellPx / 2;
          ctx.translate(cx, cy);
          ctx.scale(es.scale, es.scale);
          ctx.translate(-cx, -cy);
        }
        if (es.dy) ctx.translate(0, es.dy * cellPx);
        if (c.item.color) {
          ctx.fillStyle = c.item.color;
          cellPath(ctx, px, py, cellPx, model.cell.radius, model.cell.shape);
          ctx.fill();
        }
        if (es.flash > 0) {
          ctx.fillStyle = "rgba(255,255,255," + es.flash.toFixed(3) + ")";
          cellPath(ctx, px, py, cellPx, model.cell.radius, model.cell.shape);
          ctx.fill();
        }
        paintContent(ctx, c.item, px + cellPx / 2, py + cellPx / 2, cellPx * c.item.scale,
          itemGlyphColor(c.item, false), assets, null);
        ctx.restore();
      });

      if (model.paletteAnimated) {
        for (let y = 0; y < h; y += 1) {
          for (let x = 0; x < w; x += 1) {
            const item = model.palette[cellAt(dims.grid, x, y)];
            if (!item || !item.anim) continue;
            const a = animState(item.anim.effect, tMs, item.anim.period, item.anim.amount);
            const cx = x * pitch + cellPx / 2 + a.dx * cellPx;
            const cy = y * pitch + cellPx / 2 + a.dy * cellPx;
            ctx.save();
            ctx.globalAlpha = item.opacity * a.alpha;
            if (a.scale !== 1) {
              ctx.translate(cx, cy);
              ctx.scale(a.scale, a.scale);
              ctx.translate(-cx, -cy);
            }
            if (a.rot) {
              ctx.translate(cx, cy);
              ctx.rotate(a.rot);
              ctx.translate(-cx, -cy);
            }
            paintContent(ctx, item, cx, cy, cellPx * item.scale,
              itemGlyphColor(item, false), assets, null);
            ctx.restore();
          }
        }
        animating = true;
      }

      // ---- layers（叠加层，最多 4 层）
      model.layers.forEach((layer) => {
        const grid = resolveLayerGrid(state, layer.field);
        if (!grid) return;
        ctx.save();
        ctx.globalAlpha = layer.opacity;
        for (let y = 0; y < h; y += 1) {
          for (let x = 0; x < w; x += 1) {
            const item = layer.palette[cellAt(grid, x, y)];
            if (!item) continue;
            const px = x * pitch;
            const py = y * pitch;
            ctx.save();
            ctx.globalAlpha = layer.opacity * item.opacity;
            if (item.color) {
              ctx.fillStyle = item.color;
              cellPath(ctx, px, py, cellPx, model.cell.radius, model.cell.shape);
              ctx.fill();
            }
            paintContent(ctx, item, px + cellPx / 2, py + cellPx / 2, cellPx * item.scale,
              itemGlyphColor(item, false), assets, null);
            ctx.restore();
          }
        }
        ctx.restore();
      });

      // ---- units（z 排序 + 位置补间 + 朝向 + 归属色 + 血条 + 标签）
      const liveKeys = new Set();
      const drawn = [];
      units.forEach((u) => {
        const item = model.units[u.type] || null;
        const cxCell = clamp(u.x, -1, w);
        const cyCell = clamp(u.y, -1, h);
        liveKeys.add(u.key);
        let prev = prevUnitsRef.current.get(u.key);
        if (!prev) {
          prev = { x: cxCell, y: cyCell, fromX: cxCell, fromY: cyCell, cx: cxCell, cy: cyCell, start: tMs };
          prevUnitsRef.current.set(u.key, prev);
        } else if (prev.x !== cxCell || prev.y !== cyCell) {
          prev.fromX = Number.isFinite(prev.cx) ? prev.cx : prev.x;
          prev.fromY = Number.isFinite(prev.cy) ? prev.cy : prev.y;
          prev.x = cxCell;
          prev.y = cyCell;
          prev.start = tMs;
        }
        let dx = cxCell;
        let dy = cyCell;
        if (!instant) {
          const p = tweenProgress(tMs - prev.start);
          if (tMs - prev.start < TWEEN_MS) animating = true;
          dx = lerp(prev.fromX, cxCell, p);
          dy = lerp(prev.fromY, cyCell, p);
        }
        prev.cx = dx;
        prev.cy = dy;
        drawn.push({ u, item, dx, dy });
      });
      drawn.sort((a, b) => {
        const za = a.item ? a.item.z : 0;
        const zb = b.item ? b.item.z : 0;
        if (za !== zb) return za - zb;
        if (a.dy !== b.dy) return a.dy - b.dy;
        return a.dx - b.dx;
      });

      const bars = [];
      drawn.forEach(({ u, item, dx, dy }) => {
        const px = dx * pitch;
        const py = dy * pitch;
        const cx = px + cellPx / 2;
        const cy = py + cellPx / 2;
        const anim = item && item.anim && !instant
          ? animState(item.anim.effect, tMs, item.anim.period, item.anim.amount)
          : null;
        if (item && item.anim && !instant) animating = true;
        let enter = null;
        if (item && item.enter && !instant) {
          let st = enterRef.current.get(u.key);
          if (st === undefined) { st = tMs; enterRef.current.set(u.key, st); }
          enter = enterState(item.enter.effect, tMs - st, item.enter.ms);
          if (!enter.done) animating = true;
        }
        const opacity = (item ? item.opacity : 1) * (anim ? anim.alpha : 1) * (enter ? enter.alpha : 1);
        const scale = (item ? item.scale : 1) * (anim ? anim.scale : 1) * (enter ? enter.scale : 1);
        const ucx = cx + (anim ? anim.dx * cellPx : 0);
        const ucy = cy + (anim ? anim.dy * cellPx : 0) + (enter ? enter.dy * cellPx : 0);

        const oi = ownerIndexOf(state, item, u.raw);
        const ownerColor = oi >= 0 ? item.owner_colors[oi] : null;
        const color = ownerColor || (item ? item.color : null);

        if (item && item.bg) {
          ctx.save();
          ctx.globalAlpha = opacity;
          ctx.fillStyle = item.bg;
          cellPath(ctx, px, py, cellPx, model.cell.radius, model.cell.shape);
          ctx.fill();
          ctx.restore();
        }
        ctx.save();
        ctx.globalAlpha = clamp01(opacity, 1);
        if (anim && anim.glow > 0) {
          ctx.shadowColor = color || INK;
          ctx.shadowBlur = anim.glow * cellPx * 0.9;
        }
        let rot = 0;
        if (item && item.orient) {
          const v = Number(readUnitField(state, u.raw, item.orient.field));
          const idx = item.orient.angles.indexOf(v);
          rot = (idx >= 0 ? item.orient.angles[idx] : 0) * Math.PI / 180;
        }
        if (rot) {
          ctx.translate(ucx, ucy);
          ctx.rotate(rot);
          ctx.translate(-ucx, -ucy);
        }
        paintContent(ctx, item, ucx, ucy, cellPx * scale,
          color || (item ? itemGlyphColor(item, true) : INK), assets, "•");
        if (enter && enter.flash > 0) {
          ctx.fillStyle = "rgba(255,255,255," + enter.flash.toFixed(3) + ")";
          cellPath(ctx, px, py, cellPx, model.cell.radius, model.cell.shape);
          ctx.fill();
        }
        ctx.restore();

        if (ownerColor) {
          ctx.save();
          ctx.globalAlpha = clamp01(opacity, 1);
          ctx.strokeStyle = ownerColor;
          ctx.lineWidth = Math.max(1.5, cellPx * 0.09);
          cellPath(ctx, px + ctx.lineWidth / 2, py + ctx.lineWidth / 2,
            Math.max(1, cellPx - ctx.lineWidth), model.cell.radius, model.cell.shape);
          ctx.stroke();
          ctx.restore();
        }
        if (item && item.hp) {
          const hp = Number(readUnitField(state, u.raw, item.hp.field));
          if (Number.isFinite(hp)) {
            const maxRaw = item.hp.max_field
              ? Number(readUnitField(state, u.raw, item.hp.max_field)) : NaN;
            const max = Number.isFinite(maxRaw) && maxRaw > 0 ? maxRaw : 100;
            bars.push({ px, py, frac: clamp01(hp / max), color: item.hp.color });
          }
        }
        if (item && item.label) {
          const text = readUnitField(state, u.raw, item.label.field);
          if (text !== undefined && text !== null && text !== "") {
            const label = String(text).slice(0, 3);
            const sizePx = Math.max(7, Math.round(cellPx * 0.26));
            ctx.save();
            ctx.globalAlpha = clamp01(opacity, 1);
            ctx.font = "700 " + sizePx + "px " + INK_FONT;
            ctx.textAlign = "right";
            ctx.textBaseline = "top";
            ctx.lineWidth = Math.max(1.5, sizePx * 0.28);
            ctx.strokeStyle = "rgba(255,255,255,0.9)";
            ctx.strokeText(label, px + cellPx - sizePx * 0.25, py + sizePx * 0.18);
            ctx.fillStyle = INK;
            ctx.fillText(label, px + cellPx - sizePx * 0.25, py + sizePx * 0.18);
            ctx.restore();
          }
        }
      });

      bars.forEach((b) => {
        const bw = Math.max(4, cellPx * 0.72);
        const bh = Math.max(2, Math.round(cellPx * 0.09));
        const bx = b.px + (cellPx - bw) / 2;
        const by = b.py + cellPx - bh - Math.max(1, cellPx * 0.06);
        ctx.fillStyle = "rgba(15,23,42,0.18)";
        roundRectPath(ctx, bx, by, bw, bh, bh / 2);
        ctx.fill();
        if (b.frac > 0) {
          ctx.fillStyle = b.color;
          roundRectPath(ctx, bx, by, Math.max(bh, bw * b.frac), bh, bh / 2);
          ctx.fill();
        }
      });

      // ---- 事件叠加色
      if (ev.flash > 0) {
        ctx.fillStyle = (evColor || "#ffffff") + Math.round(ev.flash * 255).toString(16).padStart(2, "0");
        ctx.fillRect(0, 0, boardW, boardH);
      }
      if (ev.tint > 0) {
        ctx.fillStyle = (evColor || "#000000") + Math.round(ev.tint * 255).toString(16).padStart(2, "0");
        ctx.fillRect(0, 0, boardW, boardH);
      }
      if (ev.dim > 0) {
        ctx.fillStyle = "rgba(0,0,0," + ev.dim.toFixed(3) + ")";
        ctx.fillRect(0, 0, boardW, boardH);
      }
      ctx.restore();

      // 清理已消失的单位/格子状态，避免长期累积
      prevUnitsRef.current.forEach((_, key) => {
        if (!liveKeys.has(key)) { prevUnitsRef.current.delete(key); enterRef.current.delete(key); }
      });

      return animating || model.hasAnims;
    };

    const tick = (t) => {
      if (stopped) return;
      let more = false;
      try {
        more = drawFrame(t);
      } catch (err) {
        more = false;                       // 渲染异常不得冒泡打断页面
      }
      if (more && !stopped) raf = requestAnimationFrame(tick);
      else raf = 0;
    };

    if (instant) {
      try { drawFrame(t0); } catch (err) { /* ignore */ }
    } else {
      raf = requestAnimationFrame(tick);
    }
    return () => {
      stopped = true;
      if (raf) cancelAnimationFrame(raf);
    };
  }, [state, model, cellPx, boardW, boardH, gap, instant, assets, assetsVersion]);

  const handleClick = (ev) => {
    if (!interactive || !onCellClick) return;
    const canvas = canvasRef.current;
    if (!canvas || typeof canvas.getBoundingClientRect !== "function") return;
    const rect = canvas.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    const px = (ev.clientX - rect.left) * (boardW / rect.width);
    const py = (ev.clientY - rect.top) * (boardH / rect.height);
    const x = Math.floor(px / pitch);
    const y = Math.floor(py / pitch);
    if (x < 0 || y < 0 || x >= w || y >= h) return;
    onCellClick(x, y);
  };

  return (
    <div ref={wrapRef} className="w-full">
      <canvas
        ref={canvasRef}
        role="img"
        aria-label={"棋盘 " + w + "×" + h}
        onClick={handleClick}
        style={{
          width: boardW,
          height: boardH,
          maxWidth: "100%",
          display: "block",
          margin: "0 auto",
          cursor: interactive && onCellClick ? "pointer" : "default",
          touchAction: "manipulation",
        }}
      />
    </div>
  );
}
