/* 渲染 v2 · 声明式 HUD（docs/design/16 §3.4）：stat / bar / badge / text / miniboard。
   只读 state + 平台统一样式（作者不控制布局），颜色只用已校验的 #rrggbb。 */

import { getPath } from "./paths.js";
import {
  DEFAULT_CELL_BG, DEFAULT_HUD_COLOR, HUD_DIM_MAX, INK, readMiniBoard,
} from "./schema.js";

const VALUE_MAX_CHARS = 24;

function fmt(value) {
  if (value === undefined || value === null) return "—";
  if (typeof value === "number") {
    if (!Number.isFinite(value)) return "—";
    return Number.isInteger(value) ? String(value) : String(Math.round(value * 100) / 100);
  }
  if (typeof value === "boolean") return value ? "是" : "否";
  if (typeof value === "string") return value.length > VALUE_MAX_CHARS
    ? value.slice(0, VALUE_MAX_CHARS) + "…" : value;
  return "—";
}

function Label({ text }) {
  if (!text) return null;
  return (
    <span className="text-[11px] font-medium tracking-wider text-muted-foreground uppercase">
      {text}
    </span>
  );
}

function MiniBoard({ item, value }) {
  const { w, h, rows } = readMiniBoard(value, item.width, item.height);
  const size = Math.max(4, Math.min(HUD_DIM_MAX * 2, item.cell));
  return (
    <div
      className="grid"
      style={{ gridTemplateColumns: "repeat(" + w + ", " + size + "px)", gap: 1 }}
    >
      {rows.flatMap((row, y) => row.map((id, x) => {
        const cell = item.palette[id] || null;
        const bg = cell && cell.color ? cell.color : DEFAULT_CELL_BG;
        return (
          <span
            key={y + "-" + x}
            className="block"
            style={{ width: size, height: size, background: bg, borderRadius: 2 }}
          />
        );
      }))}
    </div>
  );
}

export default function Hud({ items, state }) {
  if (!Array.isArray(items) || !items.length) return null;
  return (
    <div className="mt-2 flex flex-wrap items-end gap-x-5 gap-y-2 px-1">
      {items.map((item, i) => {
        const value = getPath(state, item.path);
        const color = item.color || DEFAULT_HUD_COLOR;
        if (item.kind === "stat") {
          return (
            <div key={i} className="flex flex-col gap-0.5">
              <Label text={item.label} />
              <span className="text-base leading-none font-bold tabular-nums" style={{ color }}>
                {fmt(value)}
              </span>
            </div>
          );
        }
        if (item.kind === "badge") {
          return (
            <div key={i} className="flex flex-col gap-0.5">
              <Label text={item.label} />
              <span
                className="inline-flex w-fit items-center rounded-full border px-2 py-0.5 text-xs font-medium tabular-nums"
                style={{ color, borderColor: color + "33", background: color + "14" }}
              >
                {fmt(value)}
              </span>
            </div>
          );
        }
        if (item.kind === "bar") {
          const n = Number(value);
          const frac = Number.isFinite(n) ? Math.max(0, Math.min(1, n / item.max)) : 0;
          return (
            <div key={i} className="flex min-w-[96px] flex-col gap-1">
              <div className="flex items-baseline justify-between gap-2">
                <Label text={item.label} />
                <span className="text-xs tabular-nums text-muted-foreground">
                  {fmt(value)}/{fmt(item.max)}
                </span>
              </div>
              <span className="block h-2 w-full overflow-hidden rounded-full bg-neutral-200">
                <span
                  className="block h-full rounded-full transition-all"
                  style={{ width: (frac * 100).toFixed(1) + "%", background: color }}
                />
              </span>
            </div>
          );
        }
        if (item.kind === "miniboard") {
          return (
            <div key={i} className="flex flex-col gap-1">
              <Label text={item.label} />
              <MiniBoard item={item} value={value} />
            </div>
          );
        }
        return (
          <div key={i} className="flex min-w-0 flex-col gap-0.5">
            <Label text={item.label} />
            <span className="max-w-[240px] truncate text-sm" style={{ color: item.color || INK }}>
              {fmt(value)}
            </span>
          </div>
        );
      })}
    </div>
  );
}
