const GAME_TONE = {
  snake: "var(--lab-lime)",
  tetris: "var(--lab-cyan)",
  microrts: "var(--lab-violet)",
};

export function gameColor(game) {
  return GAME_TONE[game] || "var(--lab-amber)";
}

export function gameLabel(game) {
  if (!game) return "—";
  return String(game).toUpperCase();
}

export function relativeTime(seconds) {
  const ts = Number(seconds);
  if (!Number.isFinite(ts) || ts <= 0) return "—";
  const diff = Math.max(0, Date.now() / 1000 - ts);
  if (diff < 60) return "刚刚";
  if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`;
  if (diff < 86400 * 7) return `${Math.floor(diff / 86400)} 天前`;
  return new Date(ts * 1000).toLocaleDateString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
  });
}

export function clock(seconds) {
  const ts = Number(seconds);
  if (!Number.isFinite(ts) || ts <= 0) return "—";
  return new Date(ts * 1000).toLocaleTimeString("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatBytes(bytes) {
  const n = Number(bytes);
  if (!Number.isFinite(n) || n <= 0) return "—";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export function compactNumber(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  if (Math.abs(n) >= 10000) return `${(n / 1000).toFixed(1)}k`;
  return new Intl.NumberFormat("zh-CN").format(n);
}

export function kindLabel(kind) {
  if (kind === "model_vs_model") return "模型对战";
  if (kind === "pvp") return "排位/休闲";
  if (kind === "pve") return "人机";
  return kind || "—";
}

export function statusTone(status) {
  if (status === "finished") return "green";
  if (status === "running") return "amber";
  if (status === "queued") return "neutral";
  if (status === "failed") return "red";
  return "neutral";
}

export function statusLabel(status) {
  if (status === "finished") return "已结束";
  if (status === "running") return "进行中";
  if (status === "queued") return "排队中";
  if (status === "failed") return "失败";
  return status || "—";
}

export function outcomeOf(match) {
  const result = (match && match.result) || {};
  const winner = result.winner;
  if (winner === 0) return "P0";
  if (winner === 1) return "P1";
  return null;
}

export function participantName(match, side) {
  const models = (match && match.models) || [];
  const model = models.find((m) => m && m.side === side);
  if (model) {
    if (model.type === "ai") return `AI · ${model.strategy || "builtin"}`;
    return model.name || `MODEL #${model.model_id || "?"}`;
  }
  const players = (match && match.players) || [];
  const hit = players.find((p) => p && p.side === side);
  if (hit && hit.name) return hit.name;
  const owner = players.find((p) => p && p.side === "owner");
  if (side === "p0" && owner && owner.name) return owner.name;
  if (players[0] && players[0].name) return players[0].name;
  return side === "p0" ? "P0" : "P1";
}

export function participantType(match, side) {
  const models = (match && match.models) || [];
  const model = models.find((m) => m && m.side === side);
  if (model) return model.type === "ai" ? "ai" : "model";
  return "human";
}

export function participantSub(match, side) {
  const models = (match && match.models) || [];
  const model = models.find((m) => m && m.side === side);
  if (model) {
    if (model.type === "ai") return `AI · ${model.strategy || "builtin"}`;
    return `MODEL #${model.model_id || "?"}`;
  }
  return side.toUpperCase();
}

export function ratingDelta(match) {
  const result = (match && match.result) || {};
  if (result.damage && result.damage.length === 2) return result.damage;
  return null;
}

export function shortAction(action) {
  if (action === null || action === undefined) return "—";
  if (typeof action === "number" || typeof action === "string") return String(action);
  if (
    typeof action === "object" &&
    !Array.isArray(action) &&
    (Array.isArray(action.p0) || Array.isArray(action.p1))
  ) {
    return `P0 ${(action.p0 || []).length} 指令 · P1 ${(action.p1 || []).length} 指令`;
  }
  if (Array.isArray(action)) {
    if (action.every((item) => typeof item === "number" || typeof item === "string")) {
      return action.join(" ");
    }
    try {
      const text = JSON.stringify(action);
      return text.length > 42 ? `${text.slice(0, 39)}…` : text;
    } catch (e) {
      return "—";
    }
  }
  try {
    const text = JSON.stringify(action);
    return text.length > 42 ? `${text.slice(0, 39)}…` : text;
  } catch (e) {
    return "—";
  }
}
