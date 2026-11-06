/* 选项控件（docs/design/17 §7.3）：game.yaml 声明了 pvp.choices 或 choices。
   turn 模式下先选中、可修改，再统一提交本 tick。 */

import { useEffect, useState } from "react";
import { Send } from "lucide-react";
import { Button } from "../../lab/ui.jsx";

export default function ChoiceControls({ view, meta, caps, onAction }) {
  const choices = (Array.isArray(meta?.pvp?.choices) && meta.pvp.choices.length)
    ? meta.pvp.choices
    : (Array.isArray(meta?.choices) ? meta.choices : []);
  const [selected, setSelected] = useState(null);
  const [busy, setBusy] = useState(false);

  /* 新 tick 或失去操作权时清掉上一轮的选择。 */
  useEffect(() => { setSelected(null); }, [view?.tick]);

  const submit = async () => {
    if (selected == null || !caps.canAct || busy) return;
    setBusy(true);
    try {
      await onAction(selected, choices[selected]);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="stage-controls">
      <div className="stage-controls__row">
        <div className="stage-choices">
          {choices.map((choice, index) => (
            <button
              key={index}
              type="button"
              className={`stage-choice${selected === index ? " is-active" : ""}`}
              disabled={!caps.canAct}
              onClick={() => setSelected(index)}
            >
              {choice}
            </button>
          ))}
        </div>
        <span className="stage-grow" />
        <Button variant="primary" size="sm" disabled={!caps.canAct || selected == null || busy} onClick={submit}>
          <Send size={12} /> 提交本 tick
        </Button>
      </div>
      <div className="stage-controls__note">
        {caps.canAct ? "选中后提交；结算前可以改。" : (caps.readOnlyReason || "只读")}
      </div>
    </div>
  );
}
