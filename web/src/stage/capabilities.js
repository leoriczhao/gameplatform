/* 舞台能力位（docs/design/17 §7.5）。

   旧 spec 的 12 种手绘状态全部由这几个推导出来：
     canAct  / submittedThisTick / showClock / showTimeline /
     showChat / showRematch / showShare / readOnlyReason
   纯函数，输入 MatchView（reduceMatch 的输出）+ 回看开关，单测覆盖。

   座位只有 p0/p1 两种颜色（沿用既有约定），多出来的座位回退 neutral；
   这里只做语义推导，颜色/布局由组件决定。 */

import { findSeat, isTerminalStatus } from "./reduceMatch.js";

export const CLOCK_COUNTDOWN = "countdown";
export const CLOCK_TICK = "tick";
export const CLOCK_REALTIME = "realtime";
export const CLOCK_FINAL = "final";
export const CLOCK_REVIEW = "review";

/* 时钟形态：turn + 有截止时间才是倒计时；realtime 走节拍，不显示倒计时。 */
export function clockMode(view, reviewing = false) {
  if (!view) return CLOCK_TICK;
  if (reviewing) return CLOCK_REVIEW;
  if (isTerminalStatus(view.status)) return CLOCK_FINAL;
  if (view.clock?.kind === "realtime") return CLOCK_REALTIME;
  return view.deadline_at != null ? CLOCK_COUNTDOWN : CLOCK_TICK;
}

/* 距离截止还剩多少毫秒；用 server_offset_ms 把本地时钟对齐到服务端。 */
export function remainingMs(view, now = Date.now()) {
  if (!view || view.deadline_at == null) return null;
  const offset = Number(view.server_offset_ms) || 0;
  const deadline = Number(view.deadline_at) * 1000;   // 服务端用 time.time() 秒
  if (!Number.isFinite(deadline)) return null;
  return Math.max(0, Math.round(deadline - (now + offset)));
}

/* 人类座位：练习局的 AI 座位不算；空着的人类座位算（它还能被加入）。 */
export function humanSeats(view) {
  return (view?.seats ?? []).filter((s) => (s.controller?.type ?? "human") === "human");
}

export function openSeats(view) {
  return humanSeats(view).filter((s) => !s.occupant);
}

export function opponentSeat(view) {
  const you = view?.you?.seat;
  if (!you) return null;
  return (view?.seats ?? []).find((s) => s.seat !== you)?.seat ?? null;
}

export function canChat(view) {
  return Boolean(view?.you?.seat) && (view?.seats?.length ?? 0) > 1;
}

export function readOnlyReason(view, { reviewing = false, controller = null } = {}) {
  if (!view) return "载入中";
  if (reviewing) return "回看中";
  const status = view.status;
  if (status === "aborted") return "对局已中止";
  if (status === "cancelled") return "对局已取消";
  if (status === "finished") return "对局已结束";
  if (status === "waiting") return "等待对手加入";
  if (!view.you?.seat) return "观战中";
  if (controller && controller !== "human") return "托管中";
  if (!Array.isArray(view.to_act) || !view.to_act.includes(view.you.seat)) return "等待对手出手";
  return null;
}

export function deriveCapabilities(view, { reviewing = false, now = Date.now() } = {}) {
  const youSeat = view?.you?.seat ?? null;
  const seat = youSeat ? findSeat(view, youSeat) : null;
  const controller = seat?.controller?.type ?? null;
  const status = view?.status ?? null;
  const live = status === "waiting" || status === "active";
  const toAct = Array.isArray(view?.to_act) ? view.to_act : [];
  const canAct = Boolean(
    view && status === "active" && youSeat && controller === "human"
    && toAct.includes(youSeat) && !reviewing,
  );
  const mode = clockMode(view, reviewing);
  const humans = humanSeats(view);
  return {
    canAct,
    submittedThisTick: Boolean(seat?.submitted),
    clockMode: mode,
    showClock: mode === CLOCK_COUNTDOWN,
    remainingMs: mode === CLOCK_COUNTDOWN ? remainingMs(view, now) : null,
    showTimeline: !live || reviewing,
    showChat: canChat(view),
    showRematch: Boolean(view && status === "finished" && view.kind === "pvp"
      && youSeat && humans.length >= 2 && !reviewing),
    showShare: Boolean(view && view.visibility !== "private"),
    readOnlyReason: canAct ? null : readOnlyReason(view, { reviewing, controller }),
    isLive: live,
    isTerminal: isTerminalStatus(status),
    youSeat,
    controller,
    myTurn: canAct,
  };
}
