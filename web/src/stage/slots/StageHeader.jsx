/* StageHeader（docs/design/17 §7.2）：标题 + 模式/可见性 + 菜单。 */

import { Link } from "react-router-dom";
import { Flag, Home } from "lucide-react";
import { Pill, CopyButton } from "../../lab/ui.jsx";

const MODE_LABEL = { ranked: "RANKED", casual: "CASUAL", practice: "练习" };
const MODE_TONE = { ranked: "amber", casual: "green", practice: "neutral" };
const KIND_LABEL = { pvp: "人类对战", pve: "人机练习", model_vs_model: "模型对战" };

export default function StageHeader({ view, game, caps, actions }) {
  const title = game?.meta?.title || view?.game || "对局";
  const canResign = caps.isLive && Boolean(view?.you?.seat) && view?.status === "active";
  const lobbyPath = view?.kind === "pvp" ? `/games/${view?.game}/pvp` : `/games/${view?.game}`;

  return (
    <header className="stage-header">
      <div className="stage-header__title">
        <Link to={lobbyPath} className="stage-header__back" title="返回入口">
          <Home size={14} />
        </Link>
        <h1>{title}</h1>
        <span className="stage-header__sub">
          {KIND_LABEL[view?.kind] || view?.kind || ""}
          {view?.version ? ` · v${view.version}` : ""}
        </span>
      </div>
      <div className="stage-header__pills">
        <Pill tone={MODE_TONE[view?.mode] || "neutral"}>{MODE_LABEL[view?.mode] || view?.mode}</Pill>
        <Pill>{view?.visibility === "public" ? "PUBLIC" : view?.visibility === "private" ? "PRIVATE" : "UNLISTED"}</Pill>
        {view?.id ? <span className="stage-mono">#{view.id}</span> : null}
      </div>
      <div className="stage-header__actions">
        {caps.showShare ? (
          <CopyButton text={typeof window === "undefined" ? "" : window.location.href} label="分享" />
        ) : null}
        {canResign ? (
          <button type="button" className="lab-btn lab-btn--ghost lab-btn--xs" onClick={actions.resign}>
            <Flag size={12} /> 认输
          </button>
        ) : null}
        <Link className="lab-btn lab-btn--ghost lab-btn--xs" to={lobbyPath}>大厅</Link>
      </div>
    </header>
  );
}
