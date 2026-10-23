export function normalizeGame(game, index = 0) {
  const meta = game.meta || {};
  const board = meta.board || null;
  const contract = meta.contract || null;
  return {
    id: game.id,
    code: `ENV-${String(index + 1).padStart(2, "0")}`,
    name: meta.title || game.name || game.id,
    en: String(game.id || "").toUpperCase(),
    desc: meta.description || game.description || "",
    version: meta.version || "",
    author: game.author || null,
    pvp: Boolean(game.pvp_enabled),
    hasAi: Boolean(game.has_ai),
    meta,
    board,
    contract,
    openenvUrl: game.openenv_url || `/api/openenv/${game.id}`,
    schemaUrl: game.schema_url || `/api/openenv/${game.id}/schema`,
    pageUrl: game.page_url || `/games/${game.id}`,
    scoreBounds: game.score_bounds || null,
  };
}

export const FALLBACK_GAMES = [
  {
    id: "snake",
    name: "贪吃蛇",
    description: "20×20 网格贪吃蛇：吃食物 +1 分，撞墙/撞身死亡。相对动作（0=左转 1=直行 2=右转）",
    pvp_enabled: true,
    has_ai: true,
    meta: {
      title: "贪吃蛇",
      version: "1.1.0",
      description: "20×20 网格贪吃蛇 · 相对转向 · 内置 DQN 对手",
      board: { width: 20, height: 20, cell: { size: 30 } },
      contract: { in_shape: [1, 1334], out_shape: [1, 3], protocol: "simple" },
    },
  },
  {
    id: "tetris",
    name: "俄罗斯方块",
    description: "10×20 棋盘俄罗斯方块，7-bag 随机器，支持 PvP 与启发式基线。",
    pvp_enabled: true,
    has_ai: true,
    meta: {
      title: "俄罗斯方块",
      version: "1.0.0",
      description: "10×20 棋盘 · 7-bag 随机器 · 启发式基线",
      board: { width: 10, height: 20, cell: { size: 30 } },
      contract: { in_shape: [1, 200], out_shape: [1, 4], protocol: "simple" },
    },
  },
  {
    id: "microrts",
    name: "微 RTS",
    description: "16×16 战场 MicroRTS 规则移植，多单位复合动作与确定性脚本 bot。",
    pvp_enabled: true,
    has_ai: true,
    meta: {
      title: "微 RTS",
      version: "0.9.0",
      description: "16×16 战场 · 多单位复合动作 · 脚本 bot",
      board: { width: 16, height: 16, cell: { size: 24 } },
      contract: { in_shape: [1, 16, 16, 9], out_shape: [1, 8], protocol: "composite" },
    },
  },
];

export function envChips(game) {
  const chips = [];
  if (game.board) chips.push(`OBS ${game.board.width}×${game.board.height}`);
  const contract = game.contract || {};
  const outShape = contract.out_shape;
  if (Array.isArray(outShape) && outShape.length > 0) {
    if (outShape.length > 2 || String(contract.protocol || "").toLowerCase() === "composite") {
      chips.push("ACT COMPOSITE");
    } else {
      chips.push(`ACT ${outShape[outShape.length - 1]}D`);
    }
  } else if (contract.protocol) {
    chips.push(`ACT ${String(contract.protocol).toUpperCase()}`);
  }
  return chips;
}

const OFFICIAL_ORDER = ["snake", "tetris", "microrts"];

export function sortGames(games) {
  return [...games].sort((a, b) => {
    const ia = OFFICIAL_ORDER.indexOf(a.id);
    const ib = OFFICIAL_ORDER.indexOf(b.id);
    if (ia !== -1 || ib !== -1) {
      if (ia === -1) return 1;
      if (ib === -1) return -1;
      return ia - ib;
    }
    return String(a.id).localeCompare(String(b.id));
  });
}

export function contractRows(game) {
  const contract = game.contract || {};
  const rows = [];
  if (game.board) {
    rows.push({
      name: "board",
      type: "grid",
      shape: `[${game.board.width}, ${game.board.height}]`,
    });
  }
  if (contract.in_shape) rows.push({ name: "obs_tensor", type: "float32", shape: JSON.stringify(contract.in_shape) });
  if (contract.out_shape) rows.push({ name: "action_tensor", type: "float32", shape: JSON.stringify(contract.out_shape) });
  if (contract.obs_mode) rows.push({ name: "obs_mode", type: "string", shape: JSON.stringify(contract.obs_mode) });
  if (contract.protocol) rows.push({ name: "protocol", type: "string", shape: JSON.stringify(contract.protocol) });
  return rows.slice(0, 5);
}

export function boardSize(game) {
  if (!game.board) return { cols: 12, rows: 8 };
  return { cols: Math.min(game.board.width || 12, 16), rows: Math.min(game.board.height || 8, 12) };
}
