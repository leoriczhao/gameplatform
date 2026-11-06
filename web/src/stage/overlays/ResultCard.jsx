/* 结果卡（docs/design/17 §7.3 覆盖层优先级 4）：胜负、原因、回看、再来一局。 */

import { Link, useNavigate } from "react-router-dom";
import { History, Repeat, Share2, X } from "lucide-react";
import { Button } from "../../lab/ui.jsx";

const CAUSE_LABEL = {
  done: "正常结束",
  resigned: "对方认输",
  timeout: "超时判负",
  tick_cap: "达到 tick 上限，判平",
  engine_error: "引擎异常",
  host_cancelled: "房主取消房间",
};

export default function ResultCard({ view, caps, actions, frames, onCollapse }) {
  const navigate = useNavigate();
  const you = view?.you?.seat;
  const winner = view?.result?.winner ?? null;
  const outcome = !you ? "观战结束" : winner === you ? "你赢了" : winner == null ? "平局" : "你输了";
  const tone = !you ? "neutral" : winner === you ? "win" : winner == null ? "draw" : "loss";
  const rematch = view?.rematch || null;

  const rematchBody = (() => {
    if (!caps.showRematch) return null;
    if (!rematch || rematch.state === "expired") {
      return (
        <Button variant="primary" size="sm" onClick={actions.rematch}>
          <Repeat size={12} /> 再来一局
        </Button>
      );
    }
    if (rematch.state === "offered" && rematch.by !== you) {
      return (
        <Button variant="primary" size="sm" onClick={actions.rematch}>
          <Repeat size={12} /> 接受再来一局
        </Button>
      );
    }
    if (rematch.state === "offered") {
      return <span className="stage-card__note">已发出邀请，等待对方…</span>;
    }
    if (rematch.state === "accepted" && rematch.match_id && rematch.match_id !== view.id) {
      return (
        <Button variant="primary" size="sm" onClick={() => navigate(`/m/${rematch.match_id}`)}>
          <Repeat size={12} /> 进入新对局
        </Button>
      );
    }
    return null;
  })();

  return (
    <div className="stage-overlay stage-overlay--result">
      <div className={`stage-card stage-card--result is-${tone}`}>
        <div className="stage-card__head">
          <div className="stage-card__title">{outcome}</div>
          {onCollapse ? (
            <button type="button" className="lab-icon-btn lab-icon-btn--bare" title="收起结果卡"
              onClick={onCollapse}><X size={14} /></button>
          ) : null}
        </div>
        <p className="stage-card__desc">
          {CAUSE_LABEL[view?.result?.cause] || view?.result?.cause || "对局结束"}
          {view?.result?.tick != null ? ` · tick ${view.result.tick}` : ""}
        </p>
        <div className="stage-card__actions">
          {rematchBody}
          {frames?.maxTick > 0 ? (
            <Button variant="outline" size="sm" onClick={() => frames.openAt(0)}>
              <History size={12} /> 回看本局
            </Button>
          ) : null}
          {caps.showShare ? (
            <Button variant="ghost" size="sm"
              onClick={() => navigator.clipboard?.writeText(window.location.href)}>
              <Share2 size={12} /> 分享
            </Button>
          ) : null}
          <Link className="lab-btn lab-btn--ghost lab-btn--sm"
            to={view?.kind === "pvp" ? `/games/${view?.game}/pvp` : `/games/${view?.game}`}>
            返回大厅
          </Link>
        </div>
      </div>
    </div>
  );
}
