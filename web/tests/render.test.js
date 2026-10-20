/* 渲染 v2 纯逻辑单测（docs/design/16 §6/§8）：paths / schema / effects / assets。
   不引入 jsdom/canvas 依赖，不渲染 React 组件。 */

import test from "node:test";
import assert from "node:assert/strict";

import {
  getPath, getFirstPath, isValidPath, colorOr, numOr, intOr, clamp01, isSafeAssetPath,
  isAssetName, isVectorPath, truncateChars,
} from "../src/render/paths.js";
import {
  normalizeMeta, resolveDims, resolveUnits, collectEvents, ownerIndexOf, itemGlyphColor,
  readMiniBoard, readUnitField, unwrapMeta, cellAt, assetContext,
  DEFAULT_CELL_BG, DEFAULT_BORDER, INK,
} from "../src/render/schema.js";
import {
  animState, enterState, eventState, combineEventStates, clampAnimPeriod, clampAnimAmount,
  clampEnterMs, clampEventMs, clampShakeAmount, tweenProgress,
} from "../src/render/effects.js";
import { assetUrl } from "../src/render/assets.js";

/* --------------------------------------------------------------- paths.js */

test("getPath 只做纯取值：合法语法、数组下标、越界返回 undefined", () => {
  const obj = { a: { b: [{ c: 5 }, null] }, x0: 1 };
  assert.equal(getPath(obj, "a.b.0.c"), 5);
  assert.equal(getPath(obj, "a.b.1.c"), undefined);
  assert.equal(getPath(obj, "a.b.2.c"), undefined);
  assert.equal(getPath(obj, "a.b.length"), 2);
  assert.equal(getPath(obj, "a.missing.c"), undefined);
  assert.equal(getPath(obj, "x0"), 1);
  assert.equal(getPath(obj, "0x"), undefined);        // 首段不能是数字
  assert.equal(getPath(null, "a"), undefined);
  assert.equal(getPath(42, "a"), undefined);
  assert.equal(getPath(obj, "a.b.0.c.d"), undefined);
});

test("path 语法白名单：非法/超长/超段/含 __ 一律拒绝", () => {
  assert.ok(isValidPath("score"));
  assert.ok(isValidPath("units.0.hp"));
  assert.ok(isValidPath("a.b.c.d"));
  assert.ok(!isValidPath("a.b.c.d.e"));          // >4 段
  assert.ok(!isValidPath("a..b"));
  assert.ok(!isValidPath("1abc"));
  assert.ok(!isValidPath("a-b"));
  assert.ok(!isValidPath("a.b;alert(1)"));
  assert.ok(!isValidPath("a.__proto__"));
  assert.ok(!isValidPath("a".repeat(65)));
  assert.ok(!isValidPath(""));
  assert.ok(!isValidPath(null));
  assert.equal(getPath({}, "constructor"), undefined);
  assert.equal(getPath({}, "__proto__.polluted"), undefined);
  assert.equal(getPath({ a: { b: 1 } }, "a.toString"), undefined);
  assert.equal(getFirstPath({ side: 1 }, ["owner", "side"]), 1);
  assert.equal(getFirstPath({ owner: 0, side: 1 }, ["owner", "side"]), 0);
});

test("颜色只认 #rrggbb，其他一律丢弃；数值夹紧", () => {
  assert.equal(colorOr("#ABCDEF"), "#abcdef");
  assert.equal(colorOr("red"), null);
  assert.equal(colorOr("#fff"), null);
  assert.equal(colorOr("#12345g"), null);
  assert.equal(colorOr("rgba(0,0,0,0.5)"), null);
  assert.equal(colorOr(123), null);
  assert.equal(numOr("3", 7, 0, 10), 7);
  assert.equal(numOr(NaN, 7, 0, 10), 7);
  assert.equal(numOr(-5, 7, 0, 10), 0);
  assert.equal(numOr(99, 7, 0, 10), 10);
  assert.equal(intOr(3.6, 0, 0, 10), 4);
  assert.equal(clamp01(5, 0.5), 1);
  assert.equal(clamp01("x", 0.5), 0.5);
  assert.equal(truncateChars("🐍🐍🐍", 2), "🐍🐍");
  assert.ok(isAssetName("snake_head"));
  assert.ok(!isAssetName("Snake"));
  assert.ok(isVectorPath("M12 2C7 2 3 6 3 11z"));
  assert.ok(!isVectorPath("X1 2"));
  assert.ok(!isVectorPath("M1 2 <script>"));
  assert.ok(!isVectorPath("M" + "1 ".repeat(600)));
});

/* ------------------------------------------------------------- normalizeMeta */

const V1_META = {
  slug: "snake", title: "贪吃蛇", version: "1.0.1",
  board: {
    width: 3, height: 2,
    palette: {
      empty: { glyph: "·", color: "#F1F5F9" },
      body: { glyph: "🟩" },
      head: { glyph: "🐍" },
    },
  },
  units: { worker: { glyph: "👷", color: "#2563EB" } },
};

test("v1 meta 归一化：无新字段、几何与 v1 等价、颜色小写", () => {
  const m = normalizeMeta(V1_META);
  assert.equal(m.legacy, true);
  assert.equal(m.schema, 2);
  assert.equal(m.width, 3);
  assert.equal(m.height, 2);
  assert.equal(m.cell.declared, false);
  assert.equal(m.cell.gap, 0);                 // v1 无间隙
  assert.equal(m.cell.radius, 0);              // v1 无圆角
  assert.equal(m.cell.border.width, 1);        // v1 1px 分隔线
  assert.equal(m.cell.border.color, DEFAULT_BORDER);
  assert.equal(m.background.kind, "plain");
  assert.equal(m.background.declared, false);
  assert.equal(m.boardRenderer, "auto");
  assert.equal(m.palette.empty.glyph, "·");
  assert.equal(m.palette.empty.color, "#f1f5f9");
  assert.equal(m.palette.body.color, null);
  assert.equal(m.units.worker.glyph, "👷");
  assert.equal(m.units.worker.color, "#2563eb");
  assert.equal(m.hasAnims, false);
  assert.equal(m.hasHud, false);
  assert.equal(m.hasLayers, false);
  assert.equal(m.hasEvents, false);
  assert.equal(m.hasSprites, false);
  assert.equal(m.paletteAnimated, false);
  assert.deepEqual(m.hud, []);
  assert.deepEqual(m.layers, []);
  assert.deepEqual(m.assets, {});
  assert.deepEqual(m.sounds, {});
  assert.equal(m.renderer.enabled, false);
});

test("目录条目解包：Watch.jsx 传入 {id, meta, …} 时仍能拿到真实 meta", () => {
  const entry = { id: "snake", pvp_enabled: false, meta: V1_META };
  assert.equal(unwrapMeta(entry), V1_META);
  assert.equal(unwrapMeta(V1_META), V1_META);
  assert.equal(unwrapMeta(null), null);
  const m = normalizeMeta(entry);
  assert.equal(m.palette.empty.glyph, "·");
  assert.equal(m.width, 3);
});

test("v1 state 取值等价：缺 palette 用 #fafafa + 墨色字形，缺尺寸回退网格", () => {
  const m = normalizeMeta({ board: { palette: { empty: { glyph: "·", color: "#f1f5f9" } } } });
  const state = { board: [["empty", "unknown"], ["body"]] };
  const { w, h, grid } = resolveDims(state, m);
  assert.equal(w, 2);
  assert.equal(h, 2);
  assert.equal(cellAt(grid, 0, 0), "empty");
  assert.equal(cellAt(grid, 1, 0), "unknown");
  assert.equal(cellAt(grid, 3, 3), "empty");
  assert.equal(m.palette.unknown, undefined);
  assert.equal(DEFAULT_CELL_BG, "#fafafa");
  assert.equal(itemGlyphColor(null, false), INK);
  assert.equal(itemGlyphColor(m.palette.empty, false), INK);       // palette 无 glyph_color → 墨色
  assert.equal(itemGlyphColor({ glyph_color: "#ff0000", color: "#00ff00" }, true), "#ff0000");
  assert.equal(itemGlyphColor({ color: "#00ff00" }, true), "#00ff00"); // unit 主色
  assert.equal(itemGlyphColor({ color: "#00ff00" }, false), INK);      // palette 底色不影响字形
});

test("normalizeMeta 覆盖 v2 字段：cell/background/layers/hud/events/assets/sounds", () => {
  const m = normalizeMeta({
    slug: "tetris", version: "2.0.0",
    board: {
      schema: 2, renderer: "canvas", width: 10, height: 20,
      cell: { size: 40, gap: 2, radius: 6, shape: "circle", border: { color: "#ABCDEF", width: 3 } },
      background: { kind: "checker", colors: ["#ffffff", "#EEEEEE"], line: "#cccccc" },
      palette: {
        head: { sprite: "head", orient: { field: "direction", angles: [270, 0, 90, 180] } },
        food: {
          vector: { path: "M12 2C7 2 3 6 3 11z", color: "#EF4444" },
          anim: { effect: "pulse", period: 1200, amount: 0.12 },
        },
      },
      layers: [{ field: "overlay", palette: { fog: { color: "#0f172a", opacity: 0.35 } }, opacity: 0.9 }],
      hud: [
        { kind: "stat", label: "分数", path: "score" },
        { kind: "bar", label: "能量", path: "energy", max: 100, color: "#4f46e5" },
        { kind: "miniboard", label: "NEXT", path: "next_board", width: 4, height: 4, cell: 16,
          palette: { "0": { color: "#f1f5f9" }, "1": { color: "#00b8d9" } } },
      ],
      events: [
        { name: "eat", effect: { kind: "flash", color: "#22c55e", ms: 260 }, sound: "eat" },
        { name: "death", effect: { kind: "shake", ms: 400, amount: 6 } },
      ],
    },
    assets: { head: { file: "assets/head.png", w: 32, h: 32 } },
    sounds: { eat: { file: "assets/eat.ogg", ms: 400, volume: 0.6 } },
    units: {
      worker: {
        glyph: "👷", owner_colors: ["#2563eb", "#dc2626"], owner_field: "owner",
        hp: { field: "hp", max_field: "hp_max", color: "#22c55e" },
        label: { field: "tag" }, z: 1, shadow: true,
        enter: { effect: "pop", ms: 200 },
      },
    },
  });
  assert.equal(m.legacy, false);
  assert.equal(m.boardRenderer, "canvas");
  assert.equal(m.cell.declared, true);
  assert.deepEqual(m.cell, {
    declared: true, size: 40, gap: 2, radius: 6, shape: "circle",
    border: { color: "#abcdef", width: 3 },
  });
  assert.deepEqual(m.background, {
    declared: true, kind: "checker",
    colors: ["#ffffff", "#eeeeee"], line: "#cccccc",
  });
  assert.equal(m.palette.head.sprite, "head");           // 资源存在 → 保留
  assert.deepEqual(m.palette.head.orient.angles, [270, 0, 90, 180]);
  assert.equal(m.palette.food.vector.color, "#ef4444");
  assert.equal(m.palette.food.anim.effect, "pulse");
  assert.equal(m.hasAnims, true);
  assert.equal(m.paletteAnimated, true);
  assert.equal(m.hasSprites, true);
  assert.equal(m.hasVectors, true);
  assert.equal(m.hasEnter, true);
  assert.equal(m.layers.length, 1);
  assert.equal(m.layers[0].field, "overlay");
  assert.equal(m.layers[0].opacity, 0.9);
  assert.equal(m.hud.length, 3);
  assert.equal(m.hud[1].max, 100);
  assert.equal(m.hud[2].width, 4);
  assert.equal(m.hud[2].cell, 16);
  assert.equal(m.hud[2].palette["1"].color, "#00b8d9");
  assert.equal(m.events.eat.effect.kind, "flash");
  assert.equal(m.events.eat.sound, "eat");
  assert.equal(m.events.death.effect.amount, 6);
  assert.equal(m.sounds.eat.volume, 0.6);
  assert.equal(m.units.worker.owner_colors.length, 2);
  assert.equal(m.units.worker.hp.color, "#22c55e");
  assert.equal(m.units.worker.label.field, "tag");
  assert.equal(m.units.worker.z, 1);
  assert.equal(m.units.worker.shadow, true);
  assert.equal(m.units.worker.enter.effect, "pop");
  assert.equal(m.hasSounds, true);
  assert.equal(m.hasEvents, true);
  assert.equal(m.hasHud, true);
});

test("normalizeMeta 防御性降级：越界数字夹紧、枚举/颜色/path 非法即丢弃", () => {
  const m = normalizeMeta({
    version: 7,                       // 类型错误 → ""
    board: {
      width: 9999, height: -3, renderer: "webgl",
      cell: { size: 9999, gap: 99, radius: -5, shape: "triangle",
        border: { color: "red", width: 99 } },
      background: { kind: "noise", colors: ["nope", "#AABBCC", "#DDEEFF"], line: "blue" },
      palette: {
        a: { glyph: 123, color: "#12345g", scale: 99, opacity: 5, z: 999, shadow: "yes" },
        b: { glyph: "x".repeat(50) },
        c: { vector: { path: "X1 2" } },
        d: { anim: { effect: "explode", period: 1 } },
        e: { enter: { effect: "spin", ms: 1 } },
        f: { orient: { field: "a..b", angles: [1, 2] } },
        g: { sprite: "Missing" },
        h: null,
        "": { glyph: "x" },
        ["k".repeat(40)]: { glyph: "x" },
      },
      layers: [
        { field: "a..b", palette: { fog: { color: "#000000" } } },
        { field: "overlay", palette: null },
        { field: "overlay2", palette: { fog: { color: "#000000" } }, opacity: 9 },
      ],
      hud: [
        { kind: "chart", path: "a" },
        { kind: "stat", path: "a..b" },
        { kind: "stat", path: "a.b.c.d.e" },
        { kind: "stat", path: "__proto__" },
        { kind: "stat", label: "x".repeat(40), path: "score", color: "#ABC" },
        { kind: "bar", path: "energy", max: 1e12 },
        { kind: "miniboard", path: "next", width: 999, height: -2, cell: 999 },
      ],
      events: [
        { name: "bad", effect: { kind: "explode", ms: 1 } },
        { name: "ok", effect: { kind: "flash", ms: 99999 }, sound: "missing" },
        { name: "ok2", effect: { kind: "shake", amount: 999 } },
        null,
      ],
    },
    units: {
      worker: {
        owner_colors: ["#2563eb"],                       // 只有 1 色 → 丢弃
        hp: { field: "a..b" },                            // path 非法 → 丢弃
        label: { field: "constructor" },                  // 合法 path（自身属性不存在→渲染时忽略）
      },
      bad: "nope",
    },
    assets: {
      head: { file: "../secret.png" },                    // 非法路径 → 丢弃
      ok: { file: "assets/ok.png", w: 9999, h: -1 },
      Bad: { file: "assets/x.png" },                      // 名字非法 → 丢弃
    },
    sounds: {
      eat: { file: "assets/eat.ogg", ms: 1e9, volume: 9 },
      bad: { file: "/etc/passwd" },
    },
  });
  assert.equal(m.version, "");
  assert.equal(m.width, 64);                  // 夹紧到 BOARD_MAX
  assert.equal(m.height, 1);
  assert.equal(m.boardRenderer, "auto");
  assert.equal(m.cell.size, 64);
  assert.equal(m.cell.gap, 8);
  assert.equal(m.cell.radius, 0);
  assert.equal(m.cell.shape, "square");
  assert.equal(m.cell.border.color, DEFAULT_BORDER);
  assert.equal(m.cell.border.width, 4);
  assert.equal(m.background.kind, "plain");
  assert.equal(m.background.colors[0], "#aabbcc");     // 非法色被过滤后前移
  assert.equal(m.background.colors[1], "#ddeeff");
  assert.equal(m.background.line, DEFAULT_BORDER);
  const a = m.palette.a;
  assert.equal(a.glyph, null);
  assert.equal(a.color, null);
  assert.equal(a.scale, 2);
  assert.equal(a.opacity, 1);
  assert.equal(a.z, 10);
  assert.equal(a.shadow, false);
  assert.equal(a.drawable, false);
  assert.equal(m.palette.b.glyph.length, 8);           // 超长 glyph 截断
  assert.equal(m.palette.c.vector, null);
  assert.equal(m.palette.d.anim, null);
  assert.equal(m.palette.e.enter, null);
  assert.equal(m.palette.f.orient, null);
  assert.equal(m.palette.g.sprite, null);              // 引用不存在的资源 → 降级
  assert.equal(m.palette.h, undefined);
  assert.equal(m.palette[""], undefined);
  assert.equal(m.palette["k".repeat(40)], undefined);
  assert.equal(m.layers.length, 1);                    // 非法 field / 空 palette 丢弃
  assert.equal(m.layers[0].opacity, 1);
  assert.equal(m.hud.length, 3);
  assert.equal(m.hud[0].path, "score");
  assert.equal(m.hud[0].label.length, 16);
  assert.equal(m.hud[0].color, null);                  // #ABC 非法
  assert.equal(m.hud[1].max, 1e9);
  assert.equal(m.hud[2].width, 16);
  assert.equal(m.hud[2].height, 1);
  assert.equal(m.hud[2].cell, 32);
  assert.equal(m.events.bad, undefined);
  assert.equal(m.events.ok.sound, null);               // 引用不存在的音效
  assert.equal(m.events.ok.effect.ms, 2000);
  assert.equal(m.events.ok2.effect.amount, 12);
  assert.equal(m.units.worker.owner_colors, null);
  assert.equal(m.units.worker.hp, null);
  assert.equal(m.units.worker.label.field, "constructor");
  assert.equal(m.units.bad, undefined);
  assert.equal(m.assets.head, undefined);
  assert.equal(m.assets.ok.w, 512);
  assert.equal(m.assets.ok.h, 0);
  assert.equal(m.assets.Bad, undefined);
  assert.equal(m.sounds.eat.ms, 5000);
  assert.equal(m.sounds.eat.volume, 1);
  assert.equal(m.sounds.bad, undefined);
});

test("恶意/畸形 meta 不抛异常且不卡死", () => {
  const nasty = [
    null, undefined, 42, "board", [], true,
    { board: null, units: 5, assets: "x", sounds: [], renderer: 7 },
    { board: { palette: new Map() } },
    (() => { const o = {}; o.board = o; return o; })(),          // 自引用
    Object.defineProperty({}, "board", { get() { throw new Error("boom"); } }),
  ];
  nasty.forEach((meta) => {
    const m = normalizeMeta(meta);
    assert.equal(typeof m.cell.gap, "number");
    assert.equal(typeof m.palette, "object");
    assert.ok(Array.isArray(m.hud));
    assert.ok(m.width === null || (m.width >= 1 && m.width <= 64));
  });
  const huge = normalizeMeta({
    board: {
      width: 1e9, height: 1e9,
      palette: Object.fromEntries(Array.from({ length: 5000 }, (_, i) => ["c" + i, { glyph: "x" }])),
      hud: Array.from({ length: 5000 }, () => ({ kind: "stat", path: "score" })),
      layers: Array.from({ length: 5000 }, () => ({ field: "overlay", palette: { f: { color: "#000000" } } })),
      events: Array.from({ length: 5000 }, (_, i) => ({ name: "e" + i, effect: { kind: "flash" } })),
    },
  });
  assert.equal(huge.width, 64);
  assert.equal(huge.height, 64);
  assert.equal(Object.keys(huge.palette).length, 64);
  assert.equal(huge.hud.length, 8);
  assert.equal(huge.layers.length, 4);
  assert.equal(Object.keys(huge.events).length, 8);
  assert.equal(resolveDims({}, huge).w, 64);
});

test("state 读取助手：resolveUnits / collectEvents / ownerIndexOf", () => {
  const units = resolveUnits({
    units: [
      { id: 3, type: "worker", x: 1, y: 2 },
      { type: "base", x: "4", y: 0.5 },
      { type: "bad", x: "x", y: 1 },
      null,
      7,
    ],
  });
  assert.equal(units.length, 2);
  assert.equal(units[0].key, "id:3");
  assert.equal(units[1].key, "ix:1");
  assert.equal(units[1].x, 4);
  assert.deepEqual(collectEvents({ events: ["eat", { name: "death", x: 1, y: 2 }, 7, { x: 1 }, ""] }),
    [{ name: "eat", x: null, y: null }, { name: "death", x: 1, y: 2 }]);
  assert.deepEqual(collectEvents(null), []);
  const item = { owner_colors: ["#111111", "#222222"], owner_field: "owner" };
  assert.equal(ownerIndexOf({ owner: 1 }, item), 1);
  assert.equal(ownerIndexOf({ owner: 5 }, item), -1);
  assert.equal(ownerIndexOf({ player: 1 }, { owner_colors: ["#111111", "#222222"], owner_field: null }), 1);
  assert.equal(ownerIndexOf({ side: 0 }, { owner_colors: ["#111111", "#222222"], owner_field: null }), 0);
  assert.equal(ownerIndexOf({}, { owner_colors: ["#111111", "#222222"], owner_field: null }), -1);
  assert.equal(ownerIndexOf({ owner: 0 }, { color: "#111111" }), -1);   // 无 owner_colors
  // microrts 形态：owner/hp/label 在单位对象上，优先于 state
  const mic = { owner_colors: ["#2563eb", "#dc2626"], owner_field: null };
  assert.equal(ownerIndexOf({}, mic, { owner: 1 }), 1);
  assert.equal(ownerIndexOf({ owner: 0 }, mic, { owner: 1 }), 1);       // 单位优先
  assert.equal(ownerIndexOf({ owner: 1 }, mic, {}), 1);                 // 单位无该字段 → state
  assert.equal(ownerIndexOf({ owner: 9 }, mic, { owner: 1 }), 1);
  assert.equal(readUnitField({ hp: 3 }, { hp: 7 }, "hp"), 7);
  assert.equal(readUnitField({ hp: 3 }, {}, "hp"), 3);
  assert.equal(readUnitField({ hp: 3 }, null, "hp"), 3);
  assert.equal(readUnitField({}, {}, "missing"), undefined);
});

test("readMiniBoard：二维 / 一维+width / 补 0 / 非数组", () => {
  assert.deepEqual(readMiniBoard([["1", "0"], ["0", "1"]], 4, 4), {
    w: 4, h: 4,
    rows: [["1", "0", "0", "0"], ["0", "1", "0", "0"], ["0", "0", "0", "0"], ["0", "0", "0", "0"]],
  });
  assert.deepEqual(readMiniBoard(["1", "1", "0", "1"], 2, 2), {
    w: 2, h: 2, rows: [["1", "1"], ["0", "1"]],
  });
  assert.deepEqual(readMiniBoard(null, 2, 1), { w: 2, h: 1, rows: [["0", "0"]] });
  assert.deepEqual(readMiniBoard([1, null, {}, 2], 2, 2), {
    w: 2, h: 2, rows: [["1", "0"], ["0", "2"]],
  });
  const capped = readMiniBoard([], 999, -1);
  assert.equal(capped.w, 16);
  assert.equal(capped.h, 1);
});

/* -------------------------------------------------------------- effects.js */

test("动效参数按文档范围夹紧", () => {
  assert.equal(clampAnimPeriod(1), 200);
  assert.equal(clampAnimPeriod(999999), 5000);
  assert.equal(clampAnimPeriod("x"), 1000);
  assert.equal(clampAnimAmount(-1), 0);
  assert.equal(clampAnimAmount(9), 1);
  assert.equal(clampAnimAmount("x"), 0.15);
  assert.equal(clampEnterMs(1), 40);
  assert.equal(clampEnterMs(99999), 1000);
  assert.equal(clampEventMs(1), 80);
  assert.equal(clampEventMs(99999), 2000);
  assert.equal(clampShakeAmount(0), 0);      // backend 允许 0（不震屏）
  assert.equal(clampShakeAmount(999), 12);
});

test("常驻动效曲线：白名单内可动、参数越界不放大、未知效果中性", () => {
  const neutral = { scale: 1, alpha: 1, dx: 0, dy: 0, rot: 0, glow: 0 };
  assert.deepEqual(animState("nope", 123, 1000, 1), neutral);
  for (const effect of ["pulse", "glow", "bob", "spin", "flicker", "float"]) {
    for (const t of [0, 137, 500, 4999, 123456]) {
      const a = animState(effect, t, 999999, 999999);
      assert.ok(Number.isFinite(a.scale) && a.scale >= 0.4 && a.scale <= 1.6, effect + " scale");
      assert.ok(a.alpha >= 0 && a.alpha <= 1, effect + " alpha");
      assert.ok(Math.abs(a.dx) <= 0.3 && Math.abs(a.dy) <= 0.3, effect + " offset");
      assert.ok(Number.isFinite(a.rot));
      assert.ok(a.glow >= 0 && a.glow <= 1);
    }
  }
  // amount 夹紧到 1：pulse 峰值缩放 = 1 + 1*0.5
  const peak = Math.max(...[0, 1, 2, 3, 4, 5].map((i) => animState("pulse", i * 100, 400, 5).scale));
  assert.ok(Math.abs(peak - 1.5) < 1e-9);
  assert.equal(animState("flicker", 0, 1000, 1).alpha, 0.5);   // 1 - amount*(0.5+0.5*sin(0))
});

test("入场动效：ms 夹紧、进度单调到 1、未知效果立即完成", () => {
  const start = enterState("pop", 0, 1);
  assert.equal(start.progress, 0);
  assert.ok(Math.abs(start.scale - 0.3) < 1e-9);
  assert.equal(start.done, false);
  assert.equal(enterState("pop", 40, 1).done, true);
  assert.ok(Math.abs(enterState("pop", 40, 1).scale - 1) < 1e-9);
  assert.equal(enterState("fade", 0, 200).alpha, 0);
  assert.equal(enterState("fade", 200, 200).alpha, 1);
  assert.equal(enterState("flash", 0, 200).flash, 1);
  assert.equal(enterState("rise", 0, 200).dy, 0.6);
  assert.equal(enterState("rise", 200, 200).dy, 0);
  assert.equal(enterState("bogus", 0, 200).done, true);
  assert.equal(enterState("fade", -50, 200).progress, 0);
});

test("事件效果：flash/shake/pulse/dim/tint 衰减且夹紧", () => {
  assert.equal(eventState("flash", 0, 100, 1).flash, 1);
  assert.equal(eventState("flash", 100, 100, 1).flash, 0);
  const shake = eventState("shake", 50, 400, 999);
  assert.ok(Math.abs(shake.shakeX) <= 12 && Math.abs(shake.shakeY) <= 12);
  assert.equal(eventState("shake", 400, 400, 1).shakeX, 0);
  assert.equal(eventState("dim", 0, 200, 5).dim, 1);
  assert.equal(eventState("tint", 0, 200, -3).tint, 0);
  assert.ok(eventState("pulse", 100, 200, 1).scale > 1);
  assert.ok(Math.abs(eventState("pulse", 200, 200, 1).scale - 1) < 1e-9);
  assert.equal(eventState("bogus", 0, 200).done, true);
  assert.equal(eventState("flash", 1e9, 1e9, 1).done, true);
  const combined = combineEventStates([
    eventState("flash", 0, 200, 1), eventState("dim", 0, 200, 1), eventState("pulse", 100, 200, 1),
  ]);
  assert.equal(combined.flash, 1);
  assert.equal(combined.dim, 1);
  assert.ok(combined.scale > 1);
  assert.equal(combined.done, false);
  assert.equal(combineEventStates(null).scale, 1);
  assert.equal(tweenProgress(0), 0);
  assert.equal(tweenProgress(120), 1);
  assert.equal(tweenProgress(9999), 1);
});

/* --------------------------------------------------------------- assets.js */

test("资源 URL 构造：路径拼接 + 非法字符拒绝", () => {
  const ctx = { slug: "snake", version: "1.0.1" };
  assert.equal(assetUrl(ctx, "assets/head.png"),
    "/api/ugc/assets/snake/1.0.1/assets/head.png");
  assert.equal(assetUrl(ctx, "a b.png"), "/api/ugc/assets/snake/1.0.1/a%20b.png");
  assert.equal(assetUrl(ctx, "nested/deep/x.webp"),
    "/api/ugc/assets/snake/1.0.1/nested/deep/x.webp");
  assert.equal(assetUrl({ slug: "", version: "1" }, "a.png"), null);
  assert.equal(assetUrl({ slug: "s", version: "" }, "a.png"), null);
  assert.equal(assetUrl(null, "a.png"), null);
  assert.equal(assetUrl(ctx, "../secret.png"), null);
  assert.equal(assetUrl(ctx, "assets/../../etc/passwd"), null);
  assert.equal(assetUrl(ctx, "/etc/passwd"), null);
  assert.equal(assetUrl(ctx, "a//b.png"), null);
  assert.equal(assetUrl(ctx, "a/./b.png"), null);
  assert.equal(assetUrl(ctx, "a\\b.png"), null);
  assert.equal(assetUrl(ctx, "a#b.png"), null);
  assert.equal(assetUrl(ctx, "a?b.png"), null);
  assert.equal(assetUrl(ctx, "a%b.png"), null);
  assert.equal(assetUrl(ctx, ""), null);
  assert.equal(assetUrl(ctx, 42), null);
  assert.ok(!isSafeAssetPath("x".repeat(300) + ".png"));
  assert.equal(assetContext({ slug: "s", version: "v" }).slug, "s");
  assert.equal(assetContext(null).version, "");
});
