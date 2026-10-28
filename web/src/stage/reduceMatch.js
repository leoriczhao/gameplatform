/* 对局事件流 → MatchView（docs/design/17 §7.6）。

   纯函数：直播、回放、断线重连共用同一条状态更新路径。输入是
   `backend/match_engine.py` 的 EventLog 事件，输出是服务端 `Match.view()`
   形状的客户端视图。所有事件都带 `seq`（SSE 的 id）与 `server_time`，
   reducer 只用它们做两件事：记录续传游标、估算客户端时钟偏差。

   事件类型（见 backend/match_engine.py）：
     snapshot  MatchView + seq，每次连接的第一条，缺口过大时也会退化为它
     tick      tick / frame / actions / events / to_act / deadline_at
     submitted seat / tick（不含动作内容，避免偷看）
     timeout   seat / tick / count / max
     seat      seat / occupant / controller / presence / submitted / timeouts
     status    status / result
     mark      id / tick / kind / seat?（时间线事件刻度：timeout / chat / resign）
     rematch   state / by / match_id? / expires_at?
     ping      server_time（没有 seq）
   聊天是 REST 轮询（设计 17 §12 的 M1 实施记录），不经过 reducer。 */

export const LIVE_STATUS = ["waiting", "active"];
export const TERMINAL_STATUS = ["finished", "aborted", "cancelled"];

function normalizeSeat(raw) {
  return {
    seat: raw?.seat ?? "",
    occupant: raw?.occupant ?? null,
    controller: raw?.controller ?? { type: "human" },
    presence: raw?.presence ?? "offline",
    submitted: Boolean(raw?.submitted),
    timeouts: Number(raw?.timeouts) || 0,
  };
}

function normalizeSeats(raw) {
  return Array.isArray(raw) ? raw.map(normalizeSeat) : [];
}

/* 时钟偏差 = 服务端时间 - 本地时间；倒计时和 "已缓存到 tick N" 都用它。 */
function clockOffset(previous, event, now) {
  const serverTime = Number(event?.server_time);
  if (!Number.isFinite(serverTime)) return previous ?? 0;
  return serverTime - now;
}

export function isLiveStatus(status) {
  return LIVE_STATUS.includes(status);
}

export function isTerminalStatus(status) {
  return TERMINAL_STATUS.includes(status);
}

export function findSeat(view, seat) {
  if (!view || !Array.isArray(view.seats)) return null;
  return view.seats.find((s) => s.seat === seat) ?? null;
}

/* 座位色调沿用现有约定：p0 cyan、p1 violet，多出来的座位回退 neutral。 */
export function seatTone(seat) {
  if (seat === "p0") return "cyan";
  if (seat === "p1") return "violet";
  return "neutral";
}

export function emptyView() {
  return {
    id: "", game: "", version: null, kind: null, mode: null, visibility: null,
    invite: null, clock: {}, status: "waiting", result: null,
    seats: [], you: { seat: null }, tick: 0, frame: null, events: [],
    to_act: [], deadline_at: null, actions: null, frame_count: 0,
    rematch: null, created_at: null, chat: [], log: [], marks: [],
    seq: 0, server_time: null, server_offset_ms: 0,
  };
}

/* snapshot 是权威状态：整份替换，只保留客户端自己维护的聊天。 */
export function applySnapshot(view, event, now = Date.now()) {
  const hasFrames = Number.isFinite(event?.frames);
  const tick = Number.isFinite(event?.tick) ? event.tick : 0;
  return {
    id: event?.id ?? "",
    game: event?.game ?? "",
    version: event?.version ?? null,
    kind: event?.kind ?? null,
    mode: event?.mode ?? null,
    visibility: event?.visibility ?? null,
    invite: event?.invite ?? null,
    clock: event?.clock ?? {},
    status: event?.status ?? "waiting",
    result: event?.result ?? null,
    seats: normalizeSeats(event?.seats),
    you: { seat: event?.you?.seat ?? null },
    tick,
    frame: event?.frame ?? null,
    events: Array.isArray(event?.events) ? event.events : [],
    to_act: Array.isArray(event?.to_act) ? event.to_act : [],
    deadline_at: event?.deadline_at ?? null,
    actions: event?.actions ?? null,
    frame_count: hasFrames ? event.frames : tick + 1,
    rematch: event?.rematch ?? null,
    created_at: event?.created_at ?? null,
    chat: view?.chat ?? [],
    log: view?.log ?? [],
    marks: Array.isArray(event?.marks) ? event.marks : [],
    seq: Number.isFinite(event?.seq) ? event.seq : (view?.seq ?? 0),
    server_time: event?.server_time ?? null,
    server_offset_ms: clockOffset(view?.server_offset_ms, event, now),
  };
}

const MAX_LOG = 120;

/* 舞台侧栏的日志：最近 120 条，tick / 提交 / 超时 / 座位 / 状态 / 再来一局。 */
function appendLog(view, entry) {
  const log = [...(view.log || []), { at: Number(view.server_time) || null, ...entry }];
  return log.length > MAX_LOG ? log.slice(log.length - MAX_LOG) : log;
}

function replaceSeat(view, patch) {
  if (!patch || !patch.seat) return view;
  let seen = false;
  const seats = view.seats.map((seat) => {
    if (seat.seat !== patch.seat) return seat;
    seen = true;
    return normalizeSeat({ ...seat, ...patch });
  });
  if (!seen) seats.push(normalizeSeat(patch));
  return { ...view, seats };
}

/* 新 tick 打开时服务端的 pending 会被清空，提交状态随之复位。 */
function clearSubmissions(view) {
  return view.seats.map((seat) => (seat.submitted ? { ...seat, submitted: false } : seat));
}

export function reduceMatch(view, event, now = Date.now()) {
  if (!event || typeof event !== "object") return view;
  if (event.type === "snapshot") return applySnapshot(view, event, now);
  if (!view) return view;   // 非 snapshot 事件不能先于快照到达

  const seq = Number.isFinite(event.seq) ? event.seq : view.seq;
  const offset = clockOffset(view.server_offset_ms, event, now);
  const base = { ...view, seq, server_offset_ms: offset, server_time: event.server_time ?? view.server_time };

  switch (event.type) {
    case "tick": {
      const tick = Number.isFinite(event.tick) ? event.tick : view.tick;
      if (tick < view.tick) return base;   // 重复事件：只推进游标
      return {
        ...base,
        tick,
        frame: event.frame ?? view.frame,
        events: Array.isArray(event.events) ? event.events : [],
        to_act: Array.isArray(event.to_act) ? event.to_act : [],
        deadline_at: event.deadline_at ?? null,
        actions: event.actions ?? null,
        seats: clearSubmissions(view),
        frame_count: Math.max(view.frame_count, tick + 1),
        log: appendLog(view, { kind: "tick", tick,
          events: Array.isArray(event.events) ? event.events : [] }),
      };
    }
    case "submitted": {
      if (event.tick !== view.tick) return base;   // 迟到的旧 tick 提交
      return replaceSeat({ ...base, log: appendLog(view, { kind: "submit", seat: event.seat, tick: event.tick }) },
        { seat: event.seat, submitted: true });
    }
    case "timeout": {
      const seat = findSeat(view, event.seat);
      if (!seat) return base;
      return {
        ...base,
        seats: view.seats.map((s) => (s.seat === event.seat
          ? { ...s, timeouts: Number(event.count) || 0, submitted: false } : s)),
        log: appendLog(view, { kind: "timeout", seat: event.seat, tick: event.tick,
          count: Number(event.count) || 0, max: event.max }),
      };
    }
    case "seat":
      return replaceSeat({ ...base, log: appendLog(view, { kind: "seat", seat: event.seat,
        occupant: event.occupant ?? null, controller: event.controller ?? null,
        presence: event.presence }) }, event);
    case "status": {
      const status = event.status ?? view.status;
      const terminal = isTerminalStatus(status);
      return {
        ...base,
        status,
        result: event.result ?? null,
        to_act: terminal ? [] : view.to_act,
        deadline_at: terminal ? null : view.deadline_at,
        seats: terminal ? clearSubmissions(view) : view.seats,
        log: appendLog(view, { kind: "status", status, result: event.result ?? null }),
      };
    }
    case "mark": {
      // 时间线刻度：直播时按 id 去重；回放时同一批 mark 也从帧上还原。
      const mark = {
        id: event.id ?? null,
        tick: Number.isFinite(event.tick) ? event.tick : view.tick,
        kind: event.kind ?? "",
        seat: event.seat ?? null,
      };
      const known = (view.marks || []).some((item) => item.id != null && item.id === mark.id);
      return known ? base : { ...base, marks: [...(view.marks || []), mark] };
    }
    case "rematch":
      return { ...base, rematch: event.rematch ?? null,
        log: appendLog(view, { kind: "rematch", rematch: event.rematch ?? null }) };
    case "chat": {
      const message = event.message;
      if (!message || !message.id) return base;
      const known = view.chat.some((m) => m.id === message.id);
      return { ...base, chat: known ? view.chat : [...view.chat, message] };
    }
    case "ping":
      // ping 没有 seq；只用来校准时钟。
      return { ...view, server_time: event.server_time ?? view.server_time, server_offset_ms: offset };
    default:
      return base;
  }
}

export function reduceAll(view, events, now = Date.now()) {
  let next = view;
  for (const event of events ?? []) next = reduceMatch(next, event, now);
  return next;
}
