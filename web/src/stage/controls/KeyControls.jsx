/* 键帽控件（docs/design/17 §7.3）：声明了 controls.keys 的游戏。
   turn 模式按键即提交；relative-turn（snake）把屏幕方向换算成相对动作，
   180° 反向输入直接忽略（沿用 12 §3 的约定）。 */

import { useCallback, useEffect, useMemo } from "react";
import { Keyboard } from "lucide-react";
import { relativeAction } from "../../games.js";

const KEY_LABEL = {
  ArrowUp: "↑", ArrowDown: "↓", ArrowLeft: "←", ArrowRight: "→",
  Space: "空格", " ": "空格",
};

export default function KeyControls({ view, meta, caps, onAction }) {
  const controls = meta?.controls || {};
  const keys = controls.keys || {};
  const relative = controls.mode === "relative-turn";
  const directionField = controls.direction_field || "direction";
  const frame = view?.frame || {};
  const entries = useMemo(() => Object.entries(keys), [keys]);

  const press = useCallback((entry) => {
    if (!caps.canAct || !Array.isArray(entry)) return;
    const [value, label] = entry;
    if (relative) {
      const current = Number(frame[directionField]);
      const mapped = relativeAction(current, Number(value));
      if (mapped === null) return;          // 反向：蛇不能掉头
      onAction(mapped, label);
      return;
    }
    onAction(value, label);
  }, [caps.canAct, relative, frame, directionField, onAction]);

  useEffect(() => {
    if (!caps.canAct) return undefined;
    const onKey = (event) => {
      const hit = entries.find(([key]) => key === event.key
        || (key === "Space" && event.key === " "));
      if (!hit) return;
      event.preventDefault();
      press(hit[1]);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [caps.canAct, entries, press]);

  return (
    <div className="stage-controls">
      <div className="stage-controls__row">
        <span className="stage-controls__label"><Keyboard size={12} /> 键帽</span>
        <div className="stage-keycaps">
          {entries.map(([key, entry]) => (
            <button
              key={key}
              type="button"
              className="stage-keycap"
              disabled={!caps.canAct}
              onClick={() => press(entry)}
              title={entry?.[1] ? String(entry[1]) : key}
            >
              <kbd>{KEY_LABEL[key] || key}</kbd>
              <span>{entry?.[1] ? String(entry[1]).split("(")[0] : ""}</span>
            </button>
          ))}
        </div>
        <span className="stage-controls__note">
          {caps.canAct
            ? (relative ? "按键即提交 · 相对转向" : "按键即提交")
            : (caps.readOnlyReason || "只读")}
        </span>
      </div>
    </div>
  );
}
