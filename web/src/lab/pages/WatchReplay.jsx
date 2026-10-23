import "./watch-replay.css";
import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { toast } from "sonner";
import {
  Clapperboard,
  Pause,
  Play,
  Share2,
  SkipBack,
  SkipForward,
  Swords,
  Trophy,
} from "lucide-react";
import UgBoard from "../../components/UgBoard.jsx";
import { getJson } from "../api.js";
import { rebuildReplay } from "../../replay.js";
import { Button, Card, ErrorNote, Loading, Pill, Track } from "../ui.jsx";
import { shortAction } from "../format.js";

/* moves 存的是每 tick 双方指令，不是状态；用记录的 version/seed/options
   在同一个官方 OpenEnv WS 环境内逐 tick 重建。缺少版本/seed 时明示失败。
   数据获取、AbortController、播放计时与分享链接语义与旧 pages/WatchReplay.jsx 一致，
   仅时间轴/卡片/按钮换成 Lab UI。 */
const CAUSE_LABEL = { destroyed: "全歼", time: "时间到", resigned: "认输", timeout: "超时判负" };
const SIDE_NAME = { p0: "蓝方", p1: "红方" };
const SPEEDS = [0.5, 1, 2, 4];

export default function WatchReplay() {
  const { matchId } = useParams();
  const [replay, setReplay] = useState(null);
  const [meta, setMeta] = useState(null);
  const [states, setStates] = useState([]);
  const [progress, setProgress] = useState({ done: 0, total: 0 });
  const [idx, setIdx] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setReplay(null);
    setStates([]);
    setMeta(null);
    setError("");
    setIdx(0);
    setPlaying(false);
    setProgress({ done: 0, total: 0 });
    (async () => {
      try {
        const payload = await getJson(
          "/api/v1/matches/" + encodeURIComponent(matchId) + "/replay",
          null,
          controller.signal,
        );
        if (controller.signal.aborted) return;
        const record = payload.replay;
        setReplay(record);
        const total = (record.moves || []).length + 1;
        setProgress({ done: 0, total });
        await rebuildReplay(record, {
          signal: controller.signal,
          onProgress: (built, metadata) => {
            if (controller.signal.aborted) return;
            setStates(built);
            setMeta(metadata);
            setProgress({ done: built.length, total });
          },
        });
      } catch (e) {
        if (!controller.signal.aborted && e.name !== "AbortError") {
          setError("回放重建失败：" + e.message);
        }
      }
    })();
    return () => controller.abort();
  }, [matchId, attempt]);

  /* 播放计时：800ms / speed 一帧 */
  useEffect(() => {
    if (!playing) return undefined;
    const timer = setInterval(() => {
      setIdx((value) => {
        if (value >= states.length - 1) {
          setPlaying(false);
          return value;
        }
        return value + 1;
      });
    }, 800 / speed);
    return () => clearInterval(timer);
  }, [playing, speed, states.length]);

  const retry = useCallback(() => setAttempt((value) => value + 1), []);

  const share = async () => {
    const url = window.location.origin + "/watch/match/" + matchId;
    try {
      await navigator.clipboard.writeText(url);
      toast.success("分享链接已复制，任何人打开即可观看回放");
    } catch (e) {
      toast.warning("手动复制：" + url);
    }
  };

  const moves = (replay && replay.moves) || [];
  const result = (replay && replay.result) || {};
  const s = states[idx] || null;
  const loaded = states.length > 0;
  const loading = Boolean(replay) && !error && progress.done < progress.total;
  const maxTick = Math.max(states.length - 1, 0);
  const pct = progress.total ? Math.round((100 * progress.done) / progress.total) : 0;
  const modeLabel = replay && replay.mode === "ranked" ? "排位" : "练习";
  const winnerName =
    replay && result.winner != null
      ? ((replay.players || []).find((p) => p.side === "p" + result.winner) || {}).name ||
        "p" + result.winner
      : null;
  const current = idx > 0 ? moves[idx - 1] || null : null;
  const cause = result.cause == null ? "" : CAUSE_LABEL[result.cause] || result.cause;

  return (
    <>
      <div className="lab-page-head">
        <div className="lab-page-head__copy">
          <h1 className="lab-h1">对局回放 #{matchId}</h1>
          <p className="lab-subtitle">逐 tick 重建对局状态 · 步进 / 播放 / 调速 · 分享链接任何人可直接打开</p>
        </div>
        <div className="lab-page-head__actions">
          {replay ? (
            <Pill tone={replay.mode === "ranked" ? "amber" : "green"} dot>
              {modeLabel}
            </Pill>
          ) : null}
          <Button size="sm" variant="outline" onClick={share}>
            <Share2 size={13} />
            分享链接
          </Button>
          <Link className="lab-btn lab-btn--ghost lab-btn--sm" to="/matches">
            <Swords size={13} />
            战绩
          </Link>
        </div>
      </div>

      {!replay && !error ? <Loading label="载入回放记录" /> : null}

      {error ? <ErrorNote error={{ message: error }} onRetry={retry} /> : null}

      {replay && !error ? (
        <>
          <div className="wr-banner">
            <span className="wr-banner__icon">
              <Trophy size={15} />
            </span>
            <div className="wr-banner__copy">
              <div className="wr-banner__title">
                {(replay.players || []).length
                  ? (replay.players || [])
                      .map((p) => (SIDE_NAME[p.side] || p.side) + " " + p.name)
                      .join("  vs  ")
                  : "对局 #" + matchId}
              </div>
              <div className="wr-banner__desc">
                {result.winner == null
                  ? "平局（" + cause + "）"
                  : winnerName + " 获胜（" + cause + "）"}
                {" · 共 " + (states.length || moves.length) + " tick"}
              </div>
            </div>
            <span className="lab-mono wr-banner__meta">
              SEED {replay.seed != null ? replay.seed : "—"} · {moves.length} MOVES
            </span>
          </div>

          {loading ? (
            <div className="wr-progress">
              <Track value={pct} />
              <span className="lab-mono" style={{ fontSize: 8 }}>
                重建回放中… {progress.done}/{progress.total} tick
              </span>
            </div>
          ) : null}

          <div className="wr-layout">
            <section className="wr-board-well">
              <div className="wr-board-well__head">
                <span className="lab-card__title">
                  <Clapperboard size={12} style={{ marginRight: 5, verticalAlign: "-2px" }} />
                  REPLAY
                </span>
                <span className="lab-chip">#{matchId}</span>
              </div>
              <div className="wr-board">
                <span className="wr-board-tag">{loading || !loaded ? "BUILDING" : "REPLAY"}</span>
                <UgBoard state={s} meta={meta} instant />
              </div>
              <div className="wr-board-well__foot">
                <span className="lab-mono" style={{ fontSize: 8 }}>
                  TICK {s && s.tick != null ? s.tick : 0} · {idx} / {maxTick}
                </span>
                <span className="lab-mono wr-board-move">
                  {current ? "MOVE " + current.tick + " · " + shortAction(current.action) : "INITIAL STATE"}
                </span>
              </div>
            </section>

            <aside className="wr-side">
              <Card className="wr-card">
                <div className="lab-card__head">
                  <span className="lab-card__title">回放控制</span>
                  <span className="lab-mono" style={{ fontSize: 8 }}>PLAYBACK</span>
                </div>

                <input
                  className="wr-range"
                  type="range"
                  min={0}
                  max={maxTick}
                  value={Math.min(idx, maxTick)}
                  disabled={!loaded}
                  onChange={(event) => {
                    setPlaying(false);
                    setIdx(Number(event.target.value));
                  }}
                  aria-label="回放进度"
                />

                <div className="wr-controls">
                  <Button
                    size="xs"
                    variant="outline"
                    disabled={!loaded || idx === 0}
                    onClick={() => {
                      setPlaying(false);
                      setIdx((value) => Math.max(0, value - 1));
                    }}
                    aria-label="上一帧"
                  >
                    <SkipBack size={13} />
                  </Button>
                  <Button
                    size="xs"
                    variant="primary"
                    disabled={!loaded || (idx >= maxTick && !playing)}
                    onClick={() => setPlaying((value) => !value)}
                  >
                    {playing ? <Pause size={13} /> : <Play size={13} />}
                    {playing ? "暂停" : "播放"}
                  </Button>
                  <Button
                    size="xs"
                    variant="outline"
                    disabled={!loaded || idx >= maxTick}
                    onClick={() => {
                      setPlaying(false);
                      setIdx((value) => Math.min(maxTick, value + 1));
                    }}
                    aria-label="下一帧"
                  >
                    <SkipForward size={13} />
                  </Button>
                  <span className="wr-controls__tick">
                    TICK {idx} / {maxTick}
                  </span>
                </div>

                <hr className="lab-rule" />

                <div className="wr-speed">
                  <span className="wr-speed__label">速度</span>
                  {SPEEDS.map((value) => (
                    <button
                      type="button"
                      key={value}
                      className={"wr-speed__btn" + (speed === value ? " is-active" : "")}
                      onClick={() => setSpeed(value)}
                    >
                      {value}x
                    </button>
                  ))}
                </div>
              </Card>

              <Card className="wr-card">
                <div className="lab-card__head">
                  <span className="lab-card__title">对局信息</span>
                  <Swords size={12} style={{ color: "var(--lab-text-3)" }} />
                </div>
                <div className="lab-meta-row">
                  <span>模式</span>
                  <b>{modeLabel}</b>
                </div>
                <div className="lab-meta-row">
                  <span>SEED</span>
                  <b>{replay.seed != null ? replay.seed : "—"}</b>
                </div>
                <div className="lab-meta-row">
                  <span>版本</span>
                  <b>{replay.game_version || "—"}</b>
                </div>
                <div className="lab-meta-row">
                  <span>帧数</span>
                  <b>{moves.length}</b>
                </div>
                <hr className="lab-rule" />
                <div className="wr-stats">
                  <div className="wr-stat">
                    <span>TICK</span>
                    <b>{s && s.tick != null ? s.tick : 0}</b>
                  </div>
                  {s && s.score != null ? (
                    <div className="wr-stat">
                      <span>得分</span>
                      <b>{s.score}</b>
                    </div>
                  ) : null}
                </div>
              </Card>
            </aside>
          </div>
        </>
      ) : null}
    </>
  );
}
