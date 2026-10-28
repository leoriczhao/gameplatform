/* 等待卡（docs/design/17 §7.3 覆盖层优先级 3）：房主看邀请码，访客可入座。 */

import { useState } from "react";
import { Copy, DoorOpen, X } from "lucide-react";
import { Button } from "../../lab/ui.jsx";
import { openSeats } from "../capabilities.js";

export default function WaitingCard({ view, caps, actions, invite = null }) {
  const [code, setCode] = useState(invite || "");
  const [busy, setBusy] = useState(false);
  const seats = openSeats(view);
  const seated = Boolean(view?.you?.seat);
  const privateRoom = view?.visibility === "private";
  const inviteCode = view?.invite || invite;

  const join = async (seat) => {
    if (busy) return;
    setBusy(true);
    try {
      await actions.join(seat, privateRoom ? code.trim().toUpperCase() || null : null);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="stage-overlay stage-overlay--waiting">
      <div className="stage-card stage-card--waiting">
        {seated ? (
          <>
            <div className="stage-card__title">等待对手加入</div>
            <p className="stage-card__desc">
              对局已经开始等待，把邀请码或链接发给朋友。
            </p>
            {inviteCode ? (
              <div className="stage-invite">
                <span className="stage-invite__code">{inviteCode}</span>
                <button
                  type="button"
                  className="lab-icon-btn lab-icon-btn--bare"
                  title="复制邀请链接"
                  onClick={() => navigator.clipboard?.writeText(window.location.href)}
                >
                  <Copy size={13} />
                </button>
              </div>
            ) : null}
            <div className="stage-card__actions">
              <Button variant="danger" size="sm" onClick={actions.resign}>
                <X size={12} /> 取消房间
              </Button>
            </div>
          </>
        ) : (
          <>
            <div className="stage-card__title">
              {seats.length ? "房间在等一位玩家" : "对局尚未开始"}
            </div>
            <p className="stage-card__desc">
              {privateRoom ? "这是一个私有房间，需要邀请码才能入座。" : "入座后房主会自动开局。"}
            </p>
            {privateRoom && !inviteCode ? (
              <input
                className="lab-input"
                value={code}
                placeholder="输入邀请码"
                onChange={(event) => setCode(event.target.value.toUpperCase())}
              />
            ) : null}
            <div className="stage-card__actions">
              {seats.map((seat) => (
                <Button key={seat.seat} variant="primary" size="sm" disabled={busy}
                  onClick={() => join(seat.seat)}>
                  <DoorOpen size={12} /> 入座 {seat.seat.toUpperCase()}
                </Button>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
