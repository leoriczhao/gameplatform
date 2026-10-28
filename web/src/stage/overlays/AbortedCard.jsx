/* 中止卡（docs/design/17 §7.3）：服务器重启 / 游戏熔断 / 空闲过久。 */

import { Link } from "react-router-dom";

const REASON_LABEL = {
  server_restart: "服务器重启",
  engine_error: "游戏引擎异常",
  idle: "空闲过久",
  host_cancelled: "房主取消房间",
  tick_cap: "达到 tick 上限",
};

export default function AbortedCard({ view }) {
  const cause = view?.result?.cause;
  return (
    <div className="stage-overlay stage-overlay--result">
      <div className="stage-card stage-card--result is-draw">
        <div className="stage-card__title">对局已中止</div>
        <p className="stage-card__desc">
          {REASON_LABEL[cause] || cause || "未知原因"}
          {view?.result?.detail ? ` · ${view.result.detail}` : ""}
        </p>
        <div className="stage-card__actions">
          <Link className="lab-btn lab-btn--primary lab-btn--sm"
            to={view?.kind === "pvp" ? `/games/${view?.game}/pvp` : `/games/${view?.game}`}>
            返回大厅
          </Link>
        </div>
      </div>
    </div>
  );
}
