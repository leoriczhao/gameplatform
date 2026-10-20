/* 渲染 v2 · normalizeMeta（docs/design/16 §3）：把服务端 meta 归一化为渲染模型。
   前端把 meta 当不可信数据：任何缺失/越界/类型错误都降级到 v1 语义或丢弃该特性，
   绝不抛异常、绝不把作者字符串拼进 CSS/HTML（颜色只认 #rrggbb）。 */

import {
  colorOr, getFirstPath, getPath, intOr, isAssetName, isFiniteNumber, isValidPath,
  isPlainObject, isSafeAssetPath, isVectorPath, numOr, clamp01, pickEnum, strOr, truncateChars,
} from "./paths.js";
import {
  ANIM_EFFECTS, ENTER_EFFECTS, EVENT_EFFECTS, clampAnimAmount, clampAnimPeriod,
  clampEnterMs, clampEventMs, clampShakeAmount,
} from "./effects.js";

/* --------------------------------------------------------------- 范围常量 */

export const BOARD_MAX = 64;            // backend/ugc_pack.py MAX_BOARD
export const PALETTE_MAX = 64;
export const UNITS_MAX = 32;
export const LAYERS_MAX = 4;
export const HUD_MAX = 8;
export const EVENTS_MAX = 8;
export const ASSETS_MAX = 32;
export const SOUNDS_MAX = 16;
export const CELL_SIZE_MIN = 8;
export const CELL_SIZE_MAX = 64;
export const CELL_SIZE_DEFAULT = 32;
export const GAP_MIN = 0;
export const GAP_MAX = 8;
export const RADIUS_MIN = 0;
export const RADIUS_MAX = 24;
export const BORDER_WIDTH_MIN = 0;
export const BORDER_WIDTH_MAX = 4;
export const SCALE_MIN = 0.2;
export const SCALE_MAX = 2;
export const Z_MIN = -10;
export const Z_MAX = 10;
export const OWNER_COLORS_MIN = 2;
export const OWNER_COLORS_MAX = 4;
export const HUD_CELL_MIN = 8;
export const HUD_CELL_MAX = 32;
export const HUD_DIM_MAX = 16;          // backend: miniboard width/height 1-16
export const HUD_BAR_MAX = 1e9;
export const GLYPH_MAX_CHARS = 8;
export const LABEL_MAX_CHARS = 16;
export const EVENT_NAME_MAX_CHARS = 24;

export const BACKGROUND_KINDS = ["plain", "checker", "grid"];
export const SHAPES = ["square", "circle"];
export const RENDERERS = ["auto", "dom", "canvas"];
export const HUD_KINDS = ["stat", "bar", "badge", "text", "miniboard"];
export const OWNER_FIELDS = ["owner", "player", "side"];
export const EVENT_KINDS = EVENT_EFFECTS;

export const INK = "#19191c";
export const DEFAULT_CELL_BG = "#fafafa";       // v1：palette 无 color 时的格子底色
export const DEFAULT_BOARD_BG = "#f8fafc";
export const DEFAULT_BOARD_BG_2 = "#eef2f7";
export const DEFAULT_BORDER = "#e4e4e7";
export const DEFAULT_HP_COLOR = "#22c55e";
export const DEFAULT_HUD_COLOR = "#4f46e5";

/* --------------------------------------------------------------- 子结构 */

function normalizeVector(raw) {
  if (!isPlainObject(raw)) return null;
  if (!isVectorPath(raw.path)) return null;
  return {
    path: raw.path,
    color: colorOr(raw.color),
    fill: raw.fill !== false,      // 缺省 true（false 时描边）
  };
}

function normalizeOrient(raw) {
  if (!isPlainObject(raw)) return null;
  if (!isValidPath(raw.field)) return null;
  const angles = Array.isArray(raw.angles)
    ? raw.angles.filter(isFiniteNumber).slice(0, 8)
      .map((a) => Math.round((((a % 360) + 360) % 360) * 100) / 100)
    : [];
  if (!angles.length) return null;            // backend 要求 2-8 个；前端至少 1 个即可旋转
  return { field: raw.field, angles };
}

function normalizeAnim(raw) {
  if (!isPlainObject(raw)) return null;
  const effect = pickEnum(raw.effect, ANIM_EFFECTS, null);
  if (!effect) return null;      // 枚举不在白名单 → 忽略该特性
  return {
    effect,
    period: Math.round(clampAnimPeriod(raw.period)),
    amount: clampAnimAmount(raw.amount),
  };
}

function normalizeEnter(raw) {
  if (!isPlainObject(raw)) return null;
  const effect = pickEnum(raw.effect, ENTER_EFFECTS, null);
  if (!effect) return null;
  return { effect, ms: clampEnterMs(raw.ms) };
}

function normalizeItem(raw, ctx) {
  if (!isPlainObject(raw)) return null;
  const glyph = typeof raw.glyph === "string" ? truncateChars(raw.glyph, GLYPH_MAX_CHARS) : "";
  let sprite = isAssetName(raw.sprite) ? raw.sprite : null;
  // 引用不存在的资源 → 静默降级到 glyph
  if (sprite && !Object.prototype.hasOwnProperty.call(ctx.assets, sprite)) sprite = null;
  const item = {
    glyph: glyph.length ? glyph : null,
    color: colorOr(raw.color),
    bg: ctx.isUnit ? colorOr(raw.bg) : null,
    glyph_color: colorOr(raw.glyph_color),
    scale: numOr(raw.scale, 1, SCALE_MIN, SCALE_MAX),
    opacity: clamp01(raw.opacity, 1),
    shadow: raw.shadow === true,
    sprite,
    vector: normalizeVector(raw.vector),
    orient: normalizeOrient(raw.orient),
    anim: normalizeAnim(raw.anim),
    enter: normalizeEnter(raw.enter),
    z: intOr(raw.z, 0, Z_MIN, Z_MAX),
    owner_colors: null,
    owner_field: null,
    hp: null,
    label: null,
  };
  if (ctx.isUnit) {
    const colors = Array.isArray(raw.owner_colors)
      ? raw.owner_colors.map((c) => colorOr(c)).filter(Boolean).slice(0, OWNER_COLORS_MAX)
      : [];
    if (colors.length >= OWNER_COLORS_MIN) item.owner_colors = colors;
    item.owner_field = isValidPath(raw.owner_field) ? raw.owner_field : null;
    if (isPlainObject(raw.hp) && isValidPath(raw.hp.field)) {
      item.hp = {
        field: raw.hp.field,
        max_field: isValidPath(raw.hp.max_field) ? raw.hp.max_field : null,
        color: colorOr(raw.hp.color, DEFAULT_HP_COLOR),
      };
    }
    if (isPlainObject(raw.label) && isValidPath(raw.label.field)) {
      item.label = { field: raw.label.field };
    }
  }
  item.drawable = !!(item.glyph || item.sprite || item.vector);
  return item;
}

function normalizeItemMap(raw, opts) {
  const out = {};
  if (!isPlainObject(raw)) return out;
  const keys = Object.keys(raw).slice(0, opts.max + 32);
  let kept = 0;
  for (let i = 0; i < keys.length && kept < opts.max; i += 1) {
    const key = keys[i];
    if (typeof key !== "string" || key.length < 1 || key.length > opts.maxKeyLen) continue;
    const item = normalizeItem(raw[key], opts);
    if (!item) continue;
    out[key] = item;
    kept += 1;
  }
  return out;
}

function normalizeAssets(raw) {
  const out = {};
  if (!isPlainObject(raw)) return out;
  const keys = Object.keys(raw).slice(0, ASSETS_MAX + 32);
  let kept = 0;
  for (let i = 0; i < keys.length && kept < ASSETS_MAX; i += 1) {
    const name = keys[i];
    if (!isAssetName(name)) continue;
    const a = raw[name];
    if (!isPlainObject(a) || !isSafeAssetPath(a.file)) continue;
    out[name] = { name, file: a.file, w: intOr(a.w, 0, 0, 512), h: intOr(a.h, 0, 0, 512) };
    kept += 1;
  }
  return out;
}

function normalizeSounds(raw) {
  const out = {};
  if (!isPlainObject(raw)) return out;
  const keys = Object.keys(raw).slice(0, SOUNDS_MAX + 32);
  let kept = 0;
  for (let i = 0; i < keys.length && kept < SOUNDS_MAX; i += 1) {
    const name = keys[i];
    if (!isAssetName(name)) continue;
    const s = raw[name];
    if (!isPlainObject(s) || !isSafeAssetPath(s.file)) continue;
    out[name] = {
      name,
      file: s.file,
      ms: intOr(s.ms, 600, 10, 5000),
      volume: clamp01(s.volume, 0.8),
    };
    kept += 1;
  }
  return out;
}

function normalizeLayers(raw, assets) {
  const out = [];
  if (!Array.isArray(raw)) return out;
  for (let i = 0; i < raw.length && out.length < LAYERS_MAX; i += 1) {
    const l = raw[i];
    if (!isPlainObject(l) || !isValidPath(l.field)) continue;
    const palette = normalizeItemMap(l.palette, {
      isUnit: false, assets, max: PALETTE_MAX, maxKeyLen: 16,
    });
    if (!Object.keys(palette).length) continue;
    out.push({ field: l.field, palette, opacity: clamp01(l.opacity, 1) });
  }
  return out;
}

function normalizeHud(raw, assets) {
  const out = [];
  if (!Array.isArray(raw)) return out;
  for (let i = 0; i < raw.length && out.length < HUD_MAX; i += 1) {
    const h = raw[i];
    if (!isPlainObject(h)) continue;
    const kind = pickEnum(h.kind, HUD_KINDS, null);
    if (!kind) continue;
    if (!isValidPath(h.path)) continue;         // path 不合法 → 丢弃该 HUD 项
    const item = {
      kind,
      label: truncateChars(typeof h.label === "string" ? h.label : "", LABEL_MAX_CHARS),
      path: h.path,
      color: colorOr(h.color),
    };
    if (kind === "bar") item.max = numOr(h.max, 100, 1, HUD_BAR_MAX);
    if (kind === "miniboard") {
      item.width = intOr(h.width, 4, 1, HUD_DIM_MAX);
      item.height = intOr(h.height, 4, 1, HUD_DIM_MAX);
      item.cell = intOr(h.cell, 16, HUD_CELL_MIN, HUD_CELL_MAX);
      item.palette = normalizeItemMap(h.palette, {
        isUnit: false, assets, max: PALETTE_MAX, maxKeyLen: 16,
      });
    }
    out.push(item);
  }
  return out;
}

function normalizeEvents(raw, sounds) {
  const out = {};
  if (!Array.isArray(raw)) return out;
  let kept = 0;
  for (let i = 0; i < raw.length && kept < EVENTS_MAX; i += 1) {
    const e = raw[i];
    if (!isPlainObject(e)) continue;
    const name = truncateChars(typeof e.name === "string" ? e.name : "", EVENT_NAME_MAX_CHARS);
    if (!name) continue;
    if (!isPlainObject(e.effect)) continue;
    const kind = pickEnum(e.effect.kind, EVENT_KINDS, null);
    if (!kind) continue;                        // 效果不在白名单 → 忽略
    const effect = { kind, ms: clampEventMs(e.effect.ms), color: colorOr(e.effect.color), amount: 0 };
    if (kind === "shake") effect.amount = clampShakeAmount(e.effect.amount);
    else if (kind === "pulse") effect.amount = numOr(e.effect.amount, 0.06, 0, 1);
    else if (kind === "dim") effect.amount = numOr(e.effect.amount, 0.5, 0, 1);
    else if (kind === "tint") effect.amount = numOr(e.effect.amount, 0.25, 0, 1);
    const sound = isAssetName(e.sound) && Object.prototype.hasOwnProperty.call(sounds, e.sound)
      ? e.sound : null;
    out[name] = { name, effect, sound };
    kept += 1;
  }
  return out;
}

function normalizeCell(boardRaw) {
  const raw = isPlainObject(boardRaw.cell) ? boardRaw.cell : null;
  if (!raw) {
    // 未声明 cell 几何 → 沿用 v1 视觉：无间隙、无圆角、1px 细线分隔（docs/design/16 §3.7）
    return {
      declared: false,
      size: CELL_SIZE_DEFAULT,
      gap: 0,
      radius: 0,
      shape: "square",
      border: { color: DEFAULT_BORDER, width: 1 },
    };
  }
  const borderRaw = isPlainObject(raw.border) ? raw.border : {};
  return {
    declared: true,
    size: intOr(raw.size, CELL_SIZE_DEFAULT, CELL_SIZE_MIN, CELL_SIZE_MAX),
    gap: intOr(raw.gap, 1, GAP_MIN, GAP_MAX),
    radius: intOr(raw.radius, 4, RADIUS_MIN, RADIUS_MAX),
    shape: pickEnum(raw.shape, SHAPES, "square"),
    border: {
      color: colorOr(borderRaw.color, DEFAULT_BORDER),
      width: intOr(borderRaw.width, 0, BORDER_WIDTH_MIN, BORDER_WIDTH_MAX),
    },
  };
}

function normalizeBackground(boardRaw) {
  const raw = isPlainObject(boardRaw.background) ? boardRaw.background : null;
  const list = [];
  if (raw && Array.isArray(raw.colors)) {
    for (let i = 0; i < raw.colors.length && list.length < 2; i += 1) {
      const c = colorOr(raw.colors[i]);
      if (c) list.push(c);
    }
  }
  if (raw && !list.length) {
    const single = colorOr(raw.color);          // backend 同时接受 background.color
    if (single) list.push(single);
  }
  return {
    declared: !!raw,
    kind: raw ? pickEnum(raw.kind, BACKGROUND_KINDS, "plain") : "plain",
    colors: [list[0] || DEFAULT_BOARD_BG, list[1] || list[0] || DEFAULT_BOARD_BG_2],
    line: raw ? colorOr(raw.line, DEFAULT_BORDER) : DEFAULT_BORDER,
  };
}

/* --------------------------------------------------------------- 入口 */

function emptyModel() {
  return {
    slug: "", version: "", schema: 2, legacy: true,
    width: null, height: null,
    boardRenderer: "auto", renderer: { declared: false, enabled: false, entry: null, protocol: null, fallback: "declarative" },
    cell: normalizeCell({}),
    background: normalizeBackground({}),
    palette: {}, units: {}, layers: [], hud: [], events: {},
    assets: {}, sounds: {},
    hasAnims: false, hasEnter: false, hasSprites: false, hasVectors: false,
    hasLayers: false, hasHud: false, hasEvents: false, hasSounds: false,
    paletteAnimated: false,
  };
}

function normalizeMetaInner(meta) {
  const src = isPlainObject(meta) ? meta : {};
  const boardRaw = isPlainObject(src.board) ? src.board : {};
  const assets = normalizeAssets(src.assets);
  const sounds = normalizeSounds(src.sounds);
  const palette = normalizeItemMap(boardRaw.palette, {
    isUnit: false, assets, max: PALETTE_MAX, maxKeyLen: 16,
  });
  const units = normalizeItemMap(src.units, {
    isUnit: true, assets, max: UNITS_MAX, maxKeyLen: 32,
  });
  const layers = normalizeLayers(boardRaw.layers, assets);
  const hud = normalizeHud(boardRaw.hud, assets);
  const events = normalizeEvents(boardRaw.events, sounds);
  const rendererRaw = isPlainObject(src.renderer) ? src.renderer : {};
  const cell = normalizeCell(boardRaw);

  let hasAnims = false;
  let paletteAnimated = false;
  let hasEnter = false;
  let hasSprites = false;
  let hasVectors = false;
  const scan = (map, isPalette) => {
    Object.keys(map).forEach((k) => {
      const it = map[k];
      if (it.anim) { hasAnims = true; if (isPalette) paletteAnimated = true; }
      if (it.enter) hasEnter = true;
      if (it.sprite) hasSprites = true;
      if (it.vector) hasVectors = true;
    });
  };
  scan(palette, true);
  scan(units, false);
  layers.forEach((l) => scan(l.palette, false));
  hud.forEach((h) => { if (h.palette) scan(h.palette, false); });

  const hasV2Fields = cell.declared
    || isPlainObject(boardRaw.background)
    || (Array.isArray(boardRaw.layers) && boardRaw.layers.length > 0)
    || (Array.isArray(boardRaw.hud) && boardRaw.hud.length > 0)
    || (Array.isArray(boardRaw.events) && boardRaw.events.length > 0)
    || Object.keys(assets).length > 0
    || Object.keys(sounds).length > 0
    || !!rendererRaw.entry;

  return {
    slug: strOr(src.slug, "", 40),
    version: strOr(src.version, "", 24),
    schema: src.board && src.board.schema === 1 ? 1 : 2,
    legacy: !hasV2Fields,
    width: isFiniteNumber(boardRaw.width) ? intOr(boardRaw.width, 1, 1, BOARD_MAX) : null,
    height: isFiniteNumber(boardRaw.height) ? intOr(boardRaw.height, 1, 1, BOARD_MAX) : null,
    boardRenderer: pickEnum(boardRaw.renderer, RENDERERS, "auto"),
    renderer: {
      declared: typeof rendererRaw.entry === "string" && rendererRaw.entry.length > 0,
      // 服务端门禁：renderer_enabled 为真才允许 L3；L1 阶段先忽略（见 UgBoard TODO）
      enabled: src.renderer_enabled === true || rendererRaw.enabled === true,
      entry: strOr(rendererRaw.entry, "", 128) || null,
      protocol: rendererRaw.protocol === 1 ? 1 : null,
      fallback: pickEnum(rendererRaw.fallback, ["declarative", "none"], "declarative"),
    },
    cell,
    background: normalizeBackground(boardRaw),
    palette,
    units,
    layers,
    hud,
    events,
    assets,
    sounds,
    hasAnims,
    paletteAnimated,
    hasEnter,
    hasSprites,
    hasVectors,
    hasLayers: layers.length > 0,
    hasHud: hud.length > 0,
    hasEvents: Object.keys(events).length > 0,
    hasSounds: Object.keys(sounds).length > 0,
  };
}

/* 兼容目录条目：games.js::gameMeta() 返回的是整条目录项 {id, meta, …}（Watch.jsx 直接
   把它当 meta 传入），这里统一解包，避免渲染成空模型（只显示 cell id）。 */
export function unwrapMeta(meta) {
  if (isPlainObject(meta) && meta.board === undefined
      && isPlainObject(meta.meta) && meta.meta.board !== undefined) {
    return meta.meta;
  }
  return meta;
}

/* 任何畸形 meta 都不得抛异常：最坏情况返回空模型（渲染成 1×1 空棋盘）。 */
export function normalizeMeta(meta) {
  try {
    return normalizeMetaInner(unwrapMeta(meta));
  } catch (err) {
    return emptyModel();
  }
}

/* --------------------------------------------------------- state 读取助手 */

export function resolveGrid(state) {
  const g = isPlainObject(state) ? (state.render_board ?? state.board) : null;
  return Array.isArray(g) ? g : [];
}

export function resolveLayerGrid(state, field) {
  const g = getPath(state, field);
  return Array.isArray(g) ? g : null;
}

export function resolveDims(state, model) {
  const grid = resolveGrid(state);
  const rowLen = Array.isArray(grid[0]) ? grid[0].length : 0;
  const w = intOr(model && model.width, 0, 0, BOARD_MAX) || rowLen || 1;
  const h = intOr(model && model.height, 0, 0, BOARD_MAX) || grid.length || 1;
  return {
    w: intOr(w, 1, 1, BOARD_MAX),
    h: intOr(h, 1, 1, BOARD_MAX),
    grid,
  };
}

export function cellAt(grid, x, y) {
  if (!Array.isArray(grid)) return "empty";
  const row = grid[y];
  if (!Array.isArray(row)) return "empty";
  const v = row[x];
  if (v === null || v === undefined) return "empty";
  return typeof v === "string" || typeof v === "number" ? String(v) : "empty";
}

export function resolveUnits(state) {
  const raw = isPlainObject(state) && Array.isArray(state.units) ? state.units : [];
  const out = [];
  for (let i = 0; i < raw.length && out.length < 512; i += 1) {
    const u = raw[i];
    if (!isPlainObject(u)) continue;
    const x = Number(u.x);
    const y = Number(u.y);
    if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
    out.push({
      key: u.id !== undefined && u.id !== null ? "id:" + String(u.id) : "ix:" + String(i),
      type: typeof u.type === "string" ? u.type : "",
      x, y, raw: u,
    });
  }
  return out;
}

/* state.events → [{name,x,y}]（docs/design/16 §3.5）；不改动 state。 */
export function collectEvents(state) {
  const raw = isPlainObject(state) && Array.isArray(state.events) ? state.events : [];
  const out = [];
  for (let i = 0; i < raw.length && out.length < 32; i += 1) {
    const e = raw[i];
    if (typeof e === "string" && e) {
      out.push({ name: e, x: null, y: null });
    } else if (isPlainObject(e) && typeof e.name === "string" && e.name) {
      out.push({
        name: e.name,
        x: isFiniteNumber(e.x) ? e.x : null,
        y: isFiniteNumber(e.y) ? e.y : null,
      });
    }
  }
  return out;
}

/* 单位字段取值：先看单位对象自身（microrts 的 owner/hp/label 都在单位上），
   再回退到 state 顶层（snake 的 direction 这类全局字段）。 */
export function readUnitField(state, unitRaw, path) {
  const own = getPath(unitRaw, path);
  if (own !== undefined && own !== null) return own;
  return getPath(state, path);
}

/* 单位归属色下标：owner_field 缺省 owner/player/side；单位自身优先于 state。 */
export function ownerIndexOf(state, item, unitRaw) {
  if (!item || !item.owner_colors) return -1;
  const paths = (item.owner_field ? [item.owner_field] : []).concat(OWNER_FIELDS);
  const own = unitRaw ? getFirstPath(unitRaw, paths) : undefined;
  const v = own !== undefined ? own : getFirstPath(state, paths);
  const n = Number(v);
  if (!Number.isInteger(n) || n < 0 || n >= item.owner_colors.length) return -1;
  return n;
}

/* 字形颜色：显式 glyph_color > unit 主色 > 墨色（v1 默认文字色）。 */
export function itemGlyphColor(item, isUnit) {
  if (item && item.glyph_color) return item.glyph_color;
  if (isUnit && item && item.color) return item.color;
  return INK;
}

/* HUD miniboard 取值（docs/design/16 §3.4）：二维数组，或一维数组 + width；
   行列不足补 "0"/空，非法值按 "0" 处理。返回 {w,h,rows}，纯函数、可单测。 */
export function readMiniBoard(value, width, height) {
  const w = Math.max(1, Math.min(HUD_DIM_MAX, Number.isInteger(width) ? width : 4));
  const h = Math.max(1, Math.min(HUD_DIM_MAX, Number.isInteger(height) ? height : 4));
  const push = (v) => (typeof v === "string" || typeof v === "number" ? String(v) : "0");
  const rows = [];
  if (Array.isArray(value) && Array.isArray(value[0])) {
    for (let y = 0; y < h; y += 1) {
      const src = Array.isArray(value[y]) ? value[y] : [];
      const row = [];
      for (let x = 0; x < w; x += 1) row.push(push(src[x]));
      rows.push(row);
    }
    return { w, h, rows };
  }
  if (Array.isArray(value)) {
    for (let y = 0; y < h; y += 1) {
      const row = [];
      for (let x = 0; x < w; x += 1) row.push(push(value[y * w + x]));
      rows.push(row);
    }
    return { w, h, rows };
  }
  for (let y = 0; y < h; y += 1) {
    const row = [];
    for (let x = 0; x < w; x += 1) row.push("0");
    rows.push(row);
  }
  return { w, h, rows };
}

/* 资源 URL 所需上下文：/api/ugc/assets/{slug}/{version}/{file} */
export function assetContext(model) {
  return {
    slug: model && typeof model.slug === "string" ? model.slug : "",
    version: model && typeof model.version === "string" ? model.version : "",
  };
}
