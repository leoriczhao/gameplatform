/* 渲染 v2 · DOM 回退（docs/design/16 §6）：无障碍优先 / prefers-reduced-motion /
   board.renderer=dom / canvas 不可用时的降级路径。
   支持基础字段：glyph/color/bg/glyph_color/scale/opacity/shadow/orient/owner_colors/hp/label；
   不支持 sprite / vector / 动效 / layers（由 canvas 主路径负责）。 */

import { cn } from "../lib/utils.js";
import {
  DEFAULT_CELL_BG, INK, cellAt, itemGlyphColor, ownerIndexOf, readUnitField,
  resolveDims, resolveUnits,
} from "./schema.js";

const GLYPH_RATIO = 0.45;      // v1：36px 格子 + text-base(16px)

export default function BoardDom({
  state, model, onCellClick = null, cellSize = 36, interactive = false,
}) {
  const { w, h, grid } = resolveDims(state, model);
  const hint = model.cell.declared
    ? model.cell.size
    : (Number.isFinite(cellSize) && cellSize > 0 ? cellSize : model.cell.size);
  const px = Math.max(8, Math.round(hint));
  const gap = model.cell.gap;
  const radius = model.cell.shape === "circle" ? "50%" : (model.cell.radius > 0 ? model.cell.radius + "px" : "0");
  const canClick = interactive && !!onCellClick;

  const unitAt = new Map();
  resolveUnits(state).forEach((u) => {
    unitAt.set(Math.round(u.x) + "," + Math.round(u.y), u);
  });

  const cells = [];
  for (let y = 0; y < h; y += 1) {
    for (let x = 0; x < w; x += 1) {
      const id = cellAt(grid, x, y);
      const item = model.palette[id] || null;
      const unit = unitAt.get(x + "," + y);
      const uitem = unit ? (model.units[unit.type] || null) : null;
      const active = uitem || item;
      // v1 语义：未知 cell id 回退成 id 文本；已知条目无 glyph 时只画底色（v2 color-only 条目）
      const glyph = uitem
        ? (uitem.glyph || "•")
        : (item ? (item.glyph || "") : String(id));
      const bg = (uitem && uitem.bg) || (item && item.color)
        || (model.background.declared ? "transparent" : DEFAULT_CELL_BG);
      const oi = ownerIndexOf(state, uitem, unit ? unit.raw : null);
      const ownerColor = oi >= 0 ? uitem.owner_colors[oi] : null;
      const glyphColor = ownerColor || itemGlyphColor(active, !!uitem);
      const scale = active && active.scale ? active.scale : 1;
      let rotate = 0;
      if (uitem && uitem.orient) {
        const v = Number(readUnitField(state, unit ? unit.raw : null, uitem.orient.field));
        const idx = uitem.orient.angles.indexOf(v);
        rotate = idx >= 0 ? uitem.orient.angles[idx] : 0;
      }
      const hp = uitem && uitem.hp ? Number(readUnitField(state, unit ? unit.raw : null, uitem.hp.field)) : NaN;
      const hpMaxRaw = uitem && uitem.hp && uitem.hp.max_field
        ? Number(readUnitField(state, unit ? unit.raw : null, uitem.hp.max_field)) : NaN;
      const hpMax = Number.isFinite(hpMaxRaw) && hpMaxRaw > 0 ? hpMaxRaw : 100;
      const hpFrac = Number.isFinite(hp) ? Math.max(0, Math.min(1, hp / hpMax)) : null;
      const labelVal = uitem && uitem.label
        ? readUnitField(state, unit ? unit.raw : null, uitem.label.field) : undefined;
      const title = unit ? (uitem && uitem.glyph ? uitem.glyph : unit.type) : String(id);
      const borderStyle = model.cell.declared
        ? (model.cell.border.width > 0
          ? { borderColor: model.cell.border.color, borderWidth: model.cell.border.width + "px" }
          : { borderWidth: 0 })
        : null;

      cells.push(
        <button
          type="button"
          key={x + "-" + y}
          disabled={!canClick}
          onClick={canClick ? () => onCellClick(x, y) : undefined}
          title={title}
          aria-label={"(" + x + "," + y + ") " + title}
          className={cn(
            "relative flex items-center justify-center overflow-hidden border leading-none select-none",
            !model.cell.declared && "border-black/5",
            canClick ? "cursor-pointer hover:ring-2 hover:ring-indigo-400" : "cursor-default",
          )}
          style={{
            width: px,
            height: px,
            background: bg,
            borderRadius: radius,
            opacity: active && active.opacity !== undefined ? active.opacity : 1,
            ...(borderStyle || {}),
          }}
        >
          <span
            className="leading-none"
            style={{
              fontSize: (px * GLYPH_RATIO * scale).toFixed(1) + "px",
              color: glyphColor || INK,
              textShadow: active && active.shadow ? "0 1px 2px rgba(15,23,42,0.28)" : undefined,
              transform: rotate ? "rotate(" + rotate + "deg)" : undefined,
            }}
          >
            {glyph}
          </span>
          {hpFrac !== null && (
            <span
              aria-hidden="true"
              className="absolute bottom-0.5 left-1/2 h-1 w-3/4 -translate-x-1/2 overflow-hidden rounded-full bg-black/15"
            >
              <span
                className="block h-full rounded-full"
                style={{ width: (hpFrac * 100).toFixed(1) + "%", background: uitem.hp.color }}
              />
            </span>
          )}
          {labelVal !== undefined && labelVal !== null && labelVal !== "" && (
            <span
              aria-hidden="true"
              className="absolute top-0 right-0.5 text-[9px] font-bold text-neutral-900"
            >
              {String(labelVal).slice(0, 3)}
            </span>
          )}
        </button>,
      );
    }
  }

  return (
    <div
      className="grid"
      style={{ gridTemplateColumns: "repeat(" + w + ", " + px + "px)", gap: gap > 0 ? gap + "px" : undefined }}
    >
      {cells}
    </div>
  );
}
