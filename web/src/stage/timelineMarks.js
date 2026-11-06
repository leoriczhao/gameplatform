/* 时间线事件刻度（docs/design/17 §7.3）：把两类事件按 tick 合并成轨道刻度。

   1. 帧上的引擎事件（eat / death / attack / clear）：随帧封存，直播和回放
      都能从 /frames 读到，reducer 的 tick 事件里也带同一份 events。
   2. 服务端 mark（timeout / chat / resign）：match_engine.record_mark 按
      tick 记录，直播走 snapshot/mark 事件，回放从帧的 marks 字段还原。

   同一 tick 的多个事件合并成一个刻度（一个点 + 一条 tooltip），点击刻度
   跳到该帧。纯函数，便于单测。 */

export const MAX_MARK_TICKS = 200;

const TEXT = {
  eat: "吃到食物",
  death: "死亡",
  clear: "消行",
  attack: "攻击",
  timeout: "超时",
  chat: "聊天",
  resign: "认输",
};

const TONE = {
  eat: "good",
  clear: "good",
  attack: "danger",
  death: "danger",
  timeout: "warn",
  chat: "info",
  resign: "warn",
};

const TONE_RANK = { danger: 3, warn: 2, good: 1, info: 0 };

export function markText(kind) {
  return TEXT[kind] || String(kind || "事件");
}

export function markTone(kind) {
  return TONE[kind] || "info";
}

function normalizeTick(value) {
  const tick = Math.round(Number(value));
  return Number.isFinite(tick) && tick >= 0 ? tick : 0;
}

function addItem(byTick, seen, tick, kind, id) {
  if (id != null) {
    const key = String(id);
    if (seen.has(key)) return;
    seen.add(key);
  }
  const t = normalizeTick(tick);
  const items = byTick.get(t) || [];
  items.push({ kind: String(kind || ""), text: markText(kind), tone: markTone(kind) });
  byTick.set(t, items);
}

export function collectMarks({ frames = [], marks = [] } = {}) {
  const byTick = new Map();
  const seen = new Set();
  for (const frame of frames || []) {
    if (!frame || !Number.isFinite(frame.tick)) continue;
    for (const event of frame.events || []) addItem(byTick, seen, frame.tick, event);
    for (const mark of frame.marks || []) {
      addItem(byTick, seen, mark?.tick ?? frame.tick, mark?.kind, mark?.id);
    }
  }
  // 直播还没刷到帧时 marks 来自 snapshot / mark 事件；回放时和帧上的 marks
  // 是同一批（id 相同），去重后不会重复。
  for (const mark of marks || []) {
    if (!mark) continue;
    addItem(byTick, seen, mark.tick, mark.kind, mark.id);
  }
  const out = [...byTick.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([tick, items]) => {
      const tone = items
        .map((item) => item.tone)
        .sort((a, b) => TONE_RANK[b] - TONE_RANK[a])[0] || "info";
      return {
        tick,
        items,
        tone,
        label: "#" + tick + " " + items.map((item) => item.text).join(" · "),
      };
    });
  return out.length > MAX_MARK_TICKS ? out.slice(out.length - MAX_MARK_TICKS) : out;
}
