/* 对局/挑战记录展示助手（14 重构）：对战中心撤销后由 战绩页/模型挑战 共用。 */
const CAUSE_LABEL = { destroyed: "全歼", time: "时间到", resigned: "认输", timeout: "超时判负" };

export function resultText(m) {
  if (m.status === "queued") return "排队中…";
  if (m.status === "running") return "运行中…";
  if (m.status === "failed") return `失败：${m.result?.error || "未知错误"}`;
  const r = m.result || {};
  const cause = CAUSE_LABEL[r.cause] || r.cause || "结束";
  if (m.kind === "pvp") {
    const names = { p0: "先手", p1: "后手" };
    (m.players || []).forEach((p) => { names[p.side] = p.name; });
    return r.winner === null
      ? `平局（${cause}）`
      : `胜者 ${names[r.winner === 0 ? "p0" : "p1"]}（${cause}）`;
  }
  const a = m.models?.[0]?.name || "模型A";
  const b = m.models?.[1]?.name || "内置 AI";
  const winnerName = r.winner === null ? "平局" : r.winner === 0 ? a : b;
  return `${winnerName === "平局" ? "平局" : `胜者 ${winnerName}`}（${cause}，${r.tick ?? "?"} tick）`;
}

export const STAT_TAG_VARIANT = {
  finished: "success", failed: "destructive", running: "info",
  queued: "secondary", default: "secondary",
};

export { CAUSE_LABEL };
