/* 对局舞台容器（docs/design/17 §7.6）：
   一个布局、五个槽位，直播 / 观战 / 回放 / 分享都走 /m/:id，模式差异只体现为
   槽位的显隐和状态。数据来自 useMatch（SSE + reducer）与 useFrames（回看帧）。 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { useAuth } from "../AuthContext.jsx";
import { useGames } from "../lab/api.js";
import { EmptyState, Loading } from "../lab/ui.jsx";
import { deriveCapabilities } from "./capabilities.js";
import { useMatch } from "./useMatch.js";
import { useFrames } from "./useFrames.js";
import StageHeader from "./slots/StageHeader.jsx";
import SeatCard from "./slots/SeatCard.jsx";
import Clock from "./slots/Clock.jsx";
import StageBoard from "./slots/StageBoard.jsx";
import HudStrip from "./slots/HudStrip.jsx";
import Timeline from "./slots/Timeline.jsx";
import SidePanel from "./slots/SidePanel.jsx";
import ControlDock from "./controls/ControlDock.jsx";
import ConnectionBanner from "./overlays/ConnectionBanner.jsx";
import ReviewBanner from "./overlays/ReviewBanner.jsx";
import WaitingCard from "./overlays/WaitingCard.jsx";
import ResultCard from "./overlays/ResultCard.jsx";
import AbortedCard from "./overlays/AbortedCard.jsx";
import "./stage.css";

const ERROR_TOAST = {
  stale_tick: "局面已更新，请基于新局面操作",
  not_to_act: "本 tick 还没轮到你出手",
  invalid_action: "动作不合法",
  autopilot: "该座位正由服务端托管，先切回手动",
  seat_taken: "座位已经有人了",
  bad_invite: "邀请码无效",
};

export default function Stage({ uid: uidProp, variant = "full" }) {
  const params = useParams();
  const [search] = useSearchParams();
  const uid = uidProp || params.id;
  const invite = search.get("invite") || null;
  const { token, authReady } = useAuth();
  const games = useGames();
  const [now, setNow] = useState(() => Date.now());
  const [boardHandler, setBoardHandler] = useState(null);
  const [resultOpen, setResultOpen] = useState(true);

  const { view, error, connection, actions } = useMatch(uid, {
    token, enabled: authReady,
  });
  const frames = useFrames(uid, {
    token,
    total: view?.frame_count ?? 0,
    enabled: Boolean(view),
  });

  const game = useMemo(() => {
    const list = games.data?.games || [];
    return list.find((item) => item.id === view?.game) || null;
  }, [games.data, view?.game]);
  const meta = game?.meta || {};

  const caps = deriveCapabilities(view, { reviewing: frames.review.active, now });

  /* 时钟只在有倒计时时高频刷新。 */
  useEffect(() => {
    const interval = caps.clockMode === "countdown" ? 250 : 1000;
    const timer = setInterval(() => setNow(Date.now()), interval);
    return () => clearInterval(timer);
  }, [caps.clockMode]);

  useEffect(() => { setResultOpen(true); }, [view?.status]);

  const notify = useCallback((err) => {
    const code = err?.code;
    toast.error(ERROR_TOAST[code] || err?.message || "操作失败");
  }, []);

  const run = useCallback(async (fn, okMessage) => {
    try {
      await fn();
      if (okMessage) toast.success(okMessage);
    } catch (err) {
      notify(err);
    }
  }, [notify]);

  const stageActions = useMemo(() => ({
    submit: async (action) => {
      try {
        await actions.submit(action);
      } catch (err) {
        notify(err);
      }
    },
    resign: async () => {
      if (!window.confirm("确定认输？对局会立即结束。")) return;
      await run(actions.resign);
    },
    rematch: () => run(actions.rematch),
    join: (seat, code) => run(() => actions.join(seat, code || invite), "已入座"),
    setController: (seat, controller) => run(
      () => actions.setController(seat, controller),
      controller.type === "human" ? "已切回手动" : "已托管给服务端",
    ),
    sendChat: actions.sendChat,
  }), [actions, run, notify, invite]);

  /* Esc：回看中回到直播（设计 17 §7.8）。 */
  useEffect(() => {
    const onKey = (event) => {
      if (event.key === "Escape" && frames.review.active) {
        event.preventDefault();
        frames.backToLive();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [frames]);

  if (!uid) {
    return (
      <div className="stage stage--full">
        <EmptyState title="没有对局 id" desc="舞台地址应为 /m/:id。" />
      </div>
    );
  }

  if (!authReady || (!view && !error)) {
    return (
      <div className="stage stage--full">
        <Loading label="连接对局…" />
      </div>
    );
  }

  if (error && !view) {
    return (
      <div className="stage stage--full">
        <EmptyState
          title={error.status === 404 ? "对局不存在" : error.status === 403 ? "没有查看权限" : "无法打开对局"}
          desc={error.message || "请返回大厅重新开始。"}
          action={<Link className="lab-btn lab-btn--outline lab-btn--sm" to="/matches">返回对局列表</Link>}
        />
      </div>
    );
  }

  if (!view) return null;

  const reviewing = frames.review.active;
  const reviewFrame = reviewing ? frames.frameFor(frames.review.tick) : null;
  const displayFrame = reviewFrame?.frame ?? view.frame;
  const displayTick = reviewing ? (reviewFrame?.tick ?? frames.review.tick) : view.tick;
  const seated = Boolean(view.you?.seat);
  const terminal = view.status === "finished" || view.status === "aborted" || view.status === "cancelled";

  let card = null;
  if (view.status === "waiting" && !reviewing) {
    card = <WaitingCard view={view} caps={caps} actions={stageActions} invite={invite} />;
  } else if (view.status === "finished" && resultOpen) {
    card = (
      <ResultCard view={view} caps={caps} actions={stageActions} frames={frames}
        onCollapse={() => setResultOpen(false)} />
    );
  } else if ((view.status === "aborted" || view.status === "cancelled") && !reviewing) {
    card = <AbortedCard view={view} />;
  }

  const banner = (
    <>
      <ConnectionBanner connection={connection} view={view} />
      <ReviewBanner frames={frames} />
    </>
  );

  return (
    <div className={`stage stage--${variant}`}>
      <StageHeader view={view} game={game} caps={caps} actions={stageActions} />
      <div className="stage-seats">
        {view.seats.map((seat) => (
          <SeatCard key={seat.seat} view={view} seat={seat} caps={caps}
            actions={stageActions} invite={invite} />
        ))}
        <Clock view={view} caps={caps} now={now} tick={displayTick} />
      </div>
      <div className="stage-main">
        <div className="stage-board-wrap">
          <StageBoard meta={meta} frame={displayFrame} onCellClick={boardHandler}
            interactive={Boolean(boardHandler)} overlay={<>{banner}{card}</>} />
          <HudStrip meta={meta} frame={displayFrame} />
          <Timeline view={view} frames={frames} />
          <ControlDock view={view} meta={meta} caps={caps} onAction={stageActions.submit}
            onBoardHandler={setBoardHandler} />
          {terminal && !resultOpen && view.status === "finished" ? (
            <button type="button" className="stage-result-reopen" onClick={() => setResultOpen(true)}>
              查看结果
            </button>
          ) : null}
        </div>
        {variant === "full" ? (
          <SidePanel view={view} caps={caps} meta={meta}
            actions={stageActions} frames={frames} />
        ) : null}
      </div>
      {!seated && caps.isLive ? (
        <div className="stage-spectator">观战中 · 只有座位上的人能操作</div>
      ) : null}
    </div>
  );
}
