/* 离散动作控件（docs/design/17 §7.3）：没有标签的 discrete(n)。
   n ≤ 12 显示编号按钮，更大用 stepper；取消旧版的整数文本框。 */

import { useEffect, useState } from "react";
import { Minus, Plus, Send } from "lucide-react";
import { Button } from "../../lab/ui.jsx";

const BUTTON_LIMIT = 12;

export default function DiscreteControls({ view, meta, caps, onAction }) {
  const outShape = meta?.contract?.out_shape;
  const count = Array.isArray(outShape) ? Number(outShape[outShape.length - 1]) : NaN;
  const total = Number.isFinite(count) && count > 0 ? Math.floor(count) : 0;
  const [value, setValue] = useState(0);
  const [busy, setBusy] = useState(false);

  useEffect(() => { setValue(0); }, [view?.tick]);

  const submit = async () => {
    if (!caps.canAct || busy || total <= 0) return;
    setBusy(true);
    try {
      await onAction(value, `动作 ${value}`);
    } finally {
      setBusy(false);
    }
  };

  if (total <= 0) return null;

  return (
    <div className="stage-controls">
      <div className="stage-controls__row">
        <span className="stage-controls__label">动作 · {total} 维</span>
        {total <= BUTTON_LIMIT ? (
          <div className="stage-choices">
            {Array.from({ length: total }, (_, index) => (
              <button
                key={index}
                type="button"
                className={`stage-choice stage-choice--num${value === index ? " is-active" : ""}`}
                disabled={!caps.canAct}
                onClick={() => setValue(index)}
              >
                {index}
              </button>
            ))}
          </div>
        ) : (
          <div className="stage-stepper">
            <button type="button" className="lab-icon-btn lab-icon-btn--bare"
              disabled={!caps.canAct} onClick={() => setValue((v) => Math.max(0, v - 1))}>
              <Minus size={13} />
            </button>
            <input
              className="stage-stepper__input"
              type="number"
              min={0}
              max={total - 1}
              value={value}
              disabled={!caps.canAct}
              onChange={(event) => setValue(Math.max(0, Math.min(total - 1, Number(event.target.value) || 0)))}
            />
            <button type="button" className="lab-icon-btn lab-icon-btn--bare"
              disabled={!caps.canAct} onClick={() => setValue((v) => Math.min(total - 1, v + 1))}>
              <Plus size={13} />
            </button>
          </div>
        )}
        <span className="stage-grow" />
        <Button variant="primary" size="sm" disabled={!caps.canAct || busy} onClick={submit}>
          <Send size={12} /> 提交本 tick
        </Button>
      </div>
      <div className="stage-controls__note">
        {caps.canAct ? "选择动作后提交。" : (caps.readOnlyReason || "只读")}
      </div>
    </div>
  );
}
