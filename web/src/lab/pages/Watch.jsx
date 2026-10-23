import "./watch.css";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Eye, Home, Radio, Swords, Trophy, Users } from "lucide-react";
import UgBoard from "../../components/UgBoard.jsx";
import { getJson, useGames } from "../api.js";
import { gameLabel } from "../format.js";
import { Card, EmptyState, ErrorNote, Loading, Pill } from "../ui.jsx";

/* 观战页（06 §7 U6）：任何公开/匹配对局都可只读围观（13 G4 通用化）。
   2s 轮询会话状态；通用棋盘渲染 + 双方提交指示，无游戏专属字段。
   API/轮询/错误映射与旧 pages/Watch.jsx 完全一致，仅表现层换成 Lab UI。 */
const POLL_MS = 2000;
const SIDE_NAME = { p0: "先手", p1: "后手" };
const CAUSE_LABEL = { destroyed: "全歼", time: "时间到", resigned: "认输", timeout: "超时判负" };
const STATUS_TEXT = { waiting: "等待开始", running: "进行中", finished: "已结束", failed: "异常" };

export default function Watch() {
  const { game, sessionId } = useParams();
  const gamesQuery = useGames();
  const [sess, setSess] = useState(null);
  const [error, setError] = useState("");
  const [booted, setBooted] = useState(false);

  const meta = useMemo(() => {
    const games = (gamesQuery.data && gamesQuery.data.games) || [];
    return games.find((item) => item.id === game) || null;
  }, [gamesQuery.data, game]);

  const poll = useCallback(async () => {
    try {
      const d = await getJson(
        "/api/v1/" + encodeURIComponent(game) + "/play/sessions/" + encodeURIComponent(sessionId),
      );
      setSess(d.session);
      setError("");
    } catch (e) {
      setError(
        e.status === 403
          ? "这是私有对局，不可观战"
          : e.status === 404
            ? "对局不存在或已过期"
            : "加载失败：" + e.message,
      );
      if (e.status === 403 || e.status === 404) setSess(null);
    } finally {
      setBooted(true);
    }
  }, [game, sessionId]);

  useEffect(() => {
    setBooted(false);
    setSess(null);
    setError("");
    poll();
    const timer = setInterval(poll, POLL_MS);
    return () => clearInterval(timer);
  }, [poll]);

  const over = Boolean(sess && sess.status === "finished");
  const winnerName =
    over && sess.winner != null
      ? ((sess.players || []).find((p) => p.side === "p" + sess.winner) || {}).name ||
        "p" + sess.winner
      : null;
  const state = (sess && sess.state) || null;
  const players = (sess && sess.players) || [];
  const modeLabel = sess && sess.mode === "ranked" ? "排位" : "练习";
  const statusText = sess ? STATUS_TEXT[sess.status] || sess.status : "";

  return (
    <>
      <div className="lab-page-head">
        <div className="lab-page-head__copy">
          <h1 className="lab-h1">观战 · {game}</h1>
          <p className="lab-subtitle">只读视角：双方提交动作后回合推进，公开对局随时可围观</p>
        </div>
        <div className="lab-page-head__actions">
          {sess ? (
            <Pill tone={sess.mode === "ranked" ? "amber" : "green"} dot>
              {modeLabel}
            </Pill>
          ) : null}
          <Link className="lab-btn lab-btn--ghost lab-btn--sm" to="/matches">
            <Swords size={13} />
            战绩
          </Link>
          <Link className="lab-btn lab-btn--ghost lab-btn--sm" to="/">
            <Home size={13} />
            大厅
          </Link>
        </div>
      </div>

      {error ? <ErrorNote error={{ message: error }} onRetry={poll} /> : null}

      {!error && !sess && !booted ? <Loading label="连接对局" /> : null}

      {!error && booted && !sess ? (
        <Card>
          <EmptyState
            icon={<Eye size={17} />}
            title="没有可显示的对局"
            desc="会话可能刚被关闭，稍后会自动重试；也可以回到战绩页查看已结束的对局。"
            action={
              <Link className="lab-btn lab-btn--primary lab-btn--sm" to="/matches">
                去战绩页
              </Link>
            }
          />
        </Card>
      ) : null}

      {!error && sess ? (
        <>
          {over ? (
            <div className="watch-banner">
              <span className="watch-banner__icon">
                <Trophy size={15} />
              </span>
              <div className="watch-banner__copy">
                <div className="watch-banner__title">
                  {sess.winner == null
                    ? "对局结束：平局（" + (CAUSE_LABEL[sess.cause] || sess.cause) + "）"
                    : "对局结束：" + winnerName + " 获胜（" +
                      (CAUSE_LABEL[sess.cause] || sess.cause) + "）"}
                </div>
                <div className="watch-banner__desc">对局已结束。回放可在「战绩」页查看。</div>
              </div>
              <Link className="lab-btn lab-btn--outline lab-btn--sm" to="/matches">
                查看回放
              </Link>
            </div>
          ) : null}

          <div className="watch-layout">
            <section className="watch-board-well">
              <div className="watch-board-well__head">
                <span className="lab-card__title">LIVE BOARD</span>
                <Pill tone={over ? "green" : "amber"} dot>
                  {statusText || "进行中"}
                </Pill>
              </div>
              <div className="watch-board">
                <UgBoard state={state} meta={meta} />
              </div>
              <div className="watch-board-well__foot">
                <span className="lab-mono" style={{ fontSize: 8 }}>
                  <Radio size={10} style={{ marginRight: 5, verticalAlign: "-1px" }} />
                  每 2 秒自动刷新 · 只读
                </span>
                {gamesQuery.loading ? (
                  <span className="lab-mono" style={{ fontSize: 8 }}>载入棋盘皮肤…</span>
                ) : null}
              </div>
            </section>

            <aside className="watch-side">
              <Card className="watch-card">
                <div className="lab-card__head">
                  <span className="lab-card__title">
                    <Users size={12} style={{ marginRight: 5, verticalAlign: "-2px" }} />
                    ROOM INFO
                  </span>
                  <span className="lab-mono" style={{ fontSize: 8 }}>#{sessionId}</span>
                </div>

                <div className="watch-players">
                  {players.length === 0 ? (
                    <p className="lab-subtitle" style={{ fontSize: 11.5 }}>玩家信息尚未就绪…</p>
                  ) : (
                    players.map((p) => (
                      <div className="watch-player" key={p.side}>
                        <span className={"watch-player__side" + (p.side === "p1" ? " is-p1" : "")}>
                          {SIDE_NAME[p.side] || p.side}
                        </span>
                        <span className="watch-player__name">{p.name || "…"}</span>
                        {p.submitted ? (
                          <Pill tone="green">已提交</Pill>
                        ) : (
                          <Pill tone="neutral">等待</Pill>
                        )}
                      </div>
                    ))
                  )}
                </div>

                <hr className="lab-rule" />

                <div className="watch-stats">
                  <div className="watch-stat">
                    <span>TICK</span>
                    <b>{state && state.tick != null ? state.tick : 0}</b>
                  </div>
                  {state && state.score != null ? (
                    <div className="watch-stat">
                      <span>得分</span>
                      <b>{state.score}</b>
                    </div>
                  ) : null}
                </div>

                <hr className="lab-rule" />

                <div className="lab-meta-row">
                  <span>游戏</span>
                  <b>{gameLabel(game)}</b>
                </div>
                <div className="lab-meta-row">
                  <span>模式</span>
                  <b>{modeLabel}</b>
                </div>
                <div className="lab-meta-row">
                  <span>状态</span>
                  <b>{statusText}</b>
                </div>
                <p className="lab-mono watch-note" style={{ letterSpacing: 0 }}>
                  页面每 2 秒自动刷新。
                </p>
              </Card>

              <Card className="watch-card">
                <div className="lab-card__head">
                  <span className="lab-card__title">SPECTATOR</span>
                  <Pill tone="lime" dot>只读</Pill>
                </div>
                <p className="lab-subtitle watch-note">
                  公开对局无需登录即可围观。对局结束后，回放会出现在「战绩」页，也可以直接分享回放链接。
                </p>
                <Link className="lab-btn lab-btn--outline lab-btn--sm lab-btn--block" to="/matches">
                  <Swords size={13} />
                  战绩与回放
                </Link>
              </Card>
            </aside>
          </div>
        </>
      ) : null}
    </>
  );
}
