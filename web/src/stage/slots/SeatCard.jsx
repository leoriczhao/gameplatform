/* SeatCard（docs/design/17 §7.3）：名字、控制器、在线/提交/超时、胜负都显示在
   座位自己的卡片上，不再用棋盘下面的说明文字补。 */

import { Bot, Box, Check, Circle, Cpu, UserRound, UserPlus } from "lucide-react";
import { Pill } from "../../lab/ui.jsx";
import { seatTone } from "../reduceMatch.js";

const PRESENCE_LABEL = { online: "在线", offline: "离线", empty: "空位", server: "服务端" };

function controllerLabel(controller) {
  if (!controller || controller.type === "human") return "人类";
  if (controller.type === "ai") return `AI · ${controller.strategy || "builtin"}`;
  if (controller.type === "model") return controller.name || `模型 #${controller.model_id}`;
  if (controller.type === "bot") return "外部 bot";
  return controller.type;
}

function ControllerIcon({ type }) {
  if (type === "ai") return <Cpu size={12} />;
  if (type === "model") return <Box size={12} />;
  if (type === "bot") return <Bot size={12} />;
  return <UserRound size={12} />;
}

export default function SeatCard({ view, seat, caps, actions, invite = null }) {
  const tone = seatTone(seat.seat);
  const controller = seat.controller || { type: "human" };
  const name = seat.occupant?.name || (controller.type === "human" ? "等待加入" : controllerLabel(controller));
  const isMe = caps.youSeat === seat.seat;
  const timeouts = Number(seat.timeouts) || 0;
  const maxTimeouts = Number(view?.clock?.max_timeouts) || 5;
  const finished = view?.status === "finished";
  const winner = view?.result?.winner ?? null;
  const canJoin = !seat.occupant && controller.type === "human" && !caps.youSeat;
  const canAutopilot = isMe && view?.kind === "pve" && view?.status === "active";
  const result = finished
    ? (winner === seat.seat ? "WIN" : winner == null ? "DRAW" : "LOSS")
    : null;

  return (
    <section className={`stage-seat stage-seat--${tone}${isMe ? " is-me" : ""}${seat.occupant ? "" : " is-open"}`}>
      <div className="stage-seat__head">
        <span className="stage-seat__dot" data-presence={seat.presence || "offline"} aria-hidden="true" />
        <span className="stage-seat__name">{name}</span>
        {seat.occupant ? (
          <span className="stage-seat__ctrl" title={controllerLabel(controller)}>
            <ControllerIcon type={controller.type} />
            {controller.type === "human" ? "" : controllerLabel(controller)}
          </span>
        ) : null}
        <span className="stage-grow" />
        {result ? <Pill tone={result === "WIN" ? "green" : result === "LOSS" ? "red" : "neutral"}>{result}</Pill> : null}
        {seat.submitted && !result ? (
          <span className="stage-seat__submitted"><Check size={12} /> 已提交</span>
        ) : null}
      </div>
      <div className="stage-seat__meta">
        <span className="stage-mono">{(seat.seat || "").toUpperCase()}</span>
        <span>{PRESENCE_LABEL[seat.presence] || seat.presence || "—"}</span>
        {timeouts > 0 ? (
          <span className="stage-seat__timeouts">超时 {timeouts}/{maxTimeouts}</span>
        ) : null}
        {canAutopilot ? (
          <button
            type="button"
            className="stage-seat__link"
            onClick={() => actions.setController(seat.seat,
              controller.type === "human" ? { type: "ai" } : { type: "human" })}
          >
            {controller.type === "human" ? "托管" : "接管"}
          </button>
        ) : null}
        {canJoin ? (
          <button
            type="button"
            className="stage-seat__join"
            onClick={() => actions.join(seat.seat, invite)}
          >
            <UserPlus size={12} /> 入座 {seat.seat.toUpperCase()}
          </button>
        ) : null}
        {!seat.occupant && !canJoin && controller.type === "human" ? (
          <span className="stage-seat__hint"><Circle size={5} /> 等待加入</span>
        ) : null}
      </div>
    </section>
  );
}
