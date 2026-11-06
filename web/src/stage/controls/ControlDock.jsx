/* ControlDock（docs/design/17 §7.2）：按动作空间选择控件，规则见 pickControls.js。 */

import { pickControls, CONTROL_NONE } from "./pickControls.js";
import KeyControls from "./KeyControls.jsx";
import ChoiceControls from "./ChoiceControls.jsx";
import DiscreteControls from "./DiscreteControls.jsx";
import CompositeBuilder from "./CompositeBuilder.jsx";

export default function ControlDock({ view, meta, caps, onAction, onBoardHandler }) {
  const picked = pickControls(meta, view);
  const shared = { view, meta, caps, onAction };

  return (
    <div className="stage-dock">
      {picked.kind === "keys" ? <KeyControls {...shared} /> : null}
      {picked.kind === "choices" ? <ChoiceControls {...shared} /> : null}
      {picked.kind === "discrete" ? <DiscreteControls {...shared} /> : null}
      {picked.kind === "composite" ? (
        <CompositeBuilder {...shared} onBoardHandler={onBoardHandler} />
      ) : null}
      {picked.kind === CONTROL_NONE ? (
        <div className="stage-controls">
          <div className="stage-controls__row">
            <span className="stage-controls__label">操作</span>
            <span className="stage-note">
              {caps.readOnlyReason || "该游戏没有声明可用的操作控件"}
            </span>
          </div>
        </div>
      ) : null}
    </div>
  );
}
