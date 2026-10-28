/* SidePanel（docs/design/17 §7.3）：对局信息 / 聊天 / 日志。
   聊天是 REST 轮询（设计 17 §12 M1 记录），只有座位上的人能看能发。 */

import { useEffect, useRef, useState } from "react";
import { Send } from "lucide-react";
import { CopyButton, Tabs, EmptyState } from "../../lab/ui.jsx";
import { clock, kindLabel, relativeTime } from "../../lab/format.js";
import { seatTone } from "../reduceMatch.js";

const CLOCK_LABEL = {
  turn: "回合制",
  realtime: "实时",
};

function seatName(view, seat) {
  const hit = (view?.seats || []).find((item) => item.seat === seat);
  return hit?.occupant?.name || seat?.toUpperCase() || "—";
}

function logText(entry) {
  if (!entry) return "";
  if (entry.kind === "tick") {
    const names = (entry.events || []).map((event) => event?.name).filter(Boolean);
    return `TICK ${entry.tick}${names.length ? " · " + names.join(" / ") : ""}`;
  }
  if (entry.kind === "submit") return `${seatOfText(entry)} 已提交`;
  if (entry.kind === "timeout") return `${seatOfText(entry)} 超时 ${entry.count}/${entry.max ?? "?"}`;
  if (entry.kind === "seat") {
    const name = entry.occupant?.name;
    if (name) return `${entry.seat?.toUpperCase()} 入座 · ${name}`;
    if (entry.presence) return `${entry.seat?.toUpperCase()} · ${entry.presence === "online" ? "在线" : "离线"}`;
    return `${entry.seat?.toUpperCase()} · ${entry.controller?.type || "—"}`;
  }
  if (entry.kind === "status") return `对局状态 → ${entry.status}`;
  if (entry.kind === "rematch") return `再来一局 · ${entry.rematch?.state || "—"}`;
  return entry.kind || "";
}

function seatOfText(entry) {
  return entry?.seat ? entry.seat.toUpperCase() : "玩家";
}

export default function SidePanel({ view, caps, meta, chat, actions, frames, variant = "full" }) {
  const [tab, setTab] = useState("match");
  const [draft, setDraft] = useState("");
  const logRef = useRef(null);
  const chatRef = useRef(null);

  useEffect(() => {
    if (tab === "log" && logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
    if (tab === "chat" && chatRef.current) chatRef.current.scrollTop = chatRef.current.scrollHeight;
  }, [tab, view?.log?.length, chat.length]);

  useEffect(() => {
    if (!caps.showChat && tab === "chat") setTab("match");
  }, [caps.showChat, tab]);

  const send = async () => {
    const text = draft.trim();
    if (!text) return;
    try {
      await actions.sendChat(text);
      setDraft("");
    } catch (err) {
      /* 聊天失败不打断舞台；错误由 useMatch 的 toast 之外的地方展示 */
    }
  };

  const tabs = [
    { key: "match", label: "对局" },
    { key: "chat", label: "聊天" },
    { key: "log", label: "日志" },
  ].filter((item) => item.key !== "chat" || caps.showChat);

  const result = view?.result;
  const winnerSeat = result?.winner ?? null;

  return (
    <aside className={`stage-side${variant === "embedded" ? " stage-side--embedded" : ""}`}>
      <Tabs items={tabs} value={tab} onChange={setTab} />
      {tab === "match" ? (
        <div className="stage-side__body">
          <dl className="stage-kv">
            <dt>对局</dt><dd>{kindLabel(view?.kind)}</dd>
            <dt>模式</dt><dd>{view?.mode || "—"}</dd>
            <dt>可见性</dt><dd>{view?.visibility || "—"}</dd>
            <dt>版本</dt><dd>{view?.version || "—"}</dd>
            <dt>时钟</dt><dd>
              {CLOCK_LABEL[view?.clock?.kind] || view?.clock?.kind || "—"}
              {view?.clock?.move_timeout_s ? ` · 单步 ${view.clock.move_timeout_s}s` : ""}
            </dd>
            <dt>创建</dt><dd>{relativeTime(view?.created_at)}</dd>
            <dt>房间</dt>
            <dd className="stage-mono">{view?.id || "—"}
              {view?.id ? <CopyButton text={typeof window === "undefined" ? "" : window.location.href} /> : null}
            </dd>
          </dl>
          <div className="stage-side__seats">
            {(view?.seats || []).map((seat) => (
              <div key={seat.seat} className={`stage-side__seat stage-side__seat--${seatTone(seat.seat)}`}>
                <span className="stage-side__seat-name">{seatName(view, seat.seat)}</span>
                <span className="stage-mono">{seat.seat.toUpperCase()}</span>
                <span className="stage-grow" />
                {seat.submitted && view?.status === "active" ? <span className="stage-mono">已提交</span> : null}
              </div>
            ))}
          </div>
          {view?.status === "finished" ? (
            <p className="stage-side__note">
              胜者：{winnerSeat ? seatName(view, winnerSeat) : "平局"}
              {result?.cause ? ` · ${result.cause}` : ""}
            </p>
          ) : null}
        </div>
      ) : null}

      {tab === "chat" ? (
        <div className="stage-side__body stage-side__body--chat">
          <div className="stage-chat" ref={chatRef}>
            {chat.length === 0 ? (
              <EmptyState title="还没有消息" desc="对局内的聊天只对双方可见。" />
            ) : chat.map((message) => {
              const seat = (view?.seats || []).find((item) => item.occupant?.user_id === message.from)?.seat;
              return (
                <div key={message.id} className={`stage-chat__item stage-chat__item--${seatTone(seat)}`}>
                  <span className="stage-chat__from">{seatName(view, seat) || "玩家"}</span>
                  <span className="stage-chat__text">{message.text}</span>
                  <span className="stage-chat__at">{message.at ? clock(message.at) : ""}</span>
                </div>
              );
            })}
          </div>
          <div className="stage-chat__compose">
            <input
              className="lab-input"
              value={draft}
              maxLength={500}
              placeholder="对双方说点什么…"
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => { if (event.key === "Enter") send(); }}
            />
            <button type="button" className="lab-btn lab-btn--primary lab-btn--sm" onClick={send}>
              <Send size={12} />
            </button>
          </div>
        </div>
      ) : null}

      {tab === "log" ? (
        <div className="stage-side__body stage-side__body--log">
          <div className="stage-log" ref={logRef}>
            {(view?.log || []).map((entry, index) => (
              <div key={index} className="stage-log__row">
                <span className={`stage-log__dot stage-log__dot--${seatTone(entry.seat)}`} />
                <span className="stage-log__text">{logText(entry)}</span>
                {entry.kind === "tick" ? <span className="stage-mono">T{entry.tick}</span> : null}
              </div>
            ))}
            {!(view?.log || []).length ? <EmptyState title="暂无日志" /> : null}
          </div>
        </div>
      ) : null}
    </aside>
  );
}
