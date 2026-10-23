import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  ArrowRight,
  Bot,
  Box,
  Copy,
  Download,
  ExternalLink,
  Pause,
  Play,
  RefreshCw,
  Swords,
  Trophy,
  UserRound,
} from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../AuthContext.jsx";
import { useLabAuth } from "../AuthDialog.jsx";
import { useMatches, useMatchReplay } from "../api.js";
import MiniBoard from "../MiniBoard.jsx";
import {
  Button,
  EmptyState,
  ErrorNote,
  Loading,
  Pill,
} from "../ui.jsx";
import {
  gameColor,
  gameLabel,
  kindLabel,
  outcomeOf,
  participantName,
  participantSub,
  participantType,
  relativeTime,
  shortAction,
  statusLabel,
  statusTone,
} from "../format.js";

const FILTERS = [
  { key: "all", label: "全部" },
  { key: "model", label: "模型对战" },
  { key: "pvp", label: "PvP" },
  { key: "running", label: "进行中" },
];

function isRunning(match) {
  return match.status === "running" || match.status === "queued";
}

function ReplayRow({ match }) {
  const outcome = outcomeOf(match);
  const result = match.result || {};
  return (
    <>
      <div className="mat-row__top">
        <span className="mat-row__id">#{match.id}</span>
        <div className="lab-row" style={{ gap: 7 }}>
          {outcome ? (
            <Pill tone={outcome === "P0" ? "green" : "red"} dot>
              {outcome === "P0" ? "P0 WIN" : "P1 WIN"}
            </Pill>
          ) : result.cause ? <Pill tone="red">{String(result.cause).toUpperCase()}</Pill> : null}
          <span className="lab-mono" style={{ fontSize: 7.5 }}>{relativeTime(match.created_at)}</span>
        </div>
      </div>
      <div className="mat-row__matchup">
        {participantName(match, "p0")} <span style={{ color: "var(--lab-text-3)" }}>vs</span>{" "}
        {participantName(match, "p1")}
      </div>
      <div className="mat-row__bottom">
        <span className="mat-row__meta">
          <span style={{ color: gameColor(match.game) }}>{gameLabel(match.game)}</span>
          <span style={{ color: "var(--lab-line-2)" }}>·</span>
          {kindLabel(match.kind)}
        </span>
        <Pill tone={statusTone(match.status)}>
          {statusLabel(match.status)}
        </Pill>
      </div>
    </>
  );
}

function Scoreboard({ match, replay }) {
  const winnerSide = outcomeOf(match);
  const names = {
    p0: participantName(match, "p0"),
    p1: participantName(match, "p1"),
  };
  const models = match.models || [];
  const result = match.result || {};
  void models;
  const score = result.score;
  return (
    <div className="lab-card">
      <div className="lab-card__head">
        <span className="lab-card__title">MATCH RESULT</span>
        <Pill tone={statusTone(match.status)}>{statusLabel(match.status)}</Pill>
      </div>
      {["p0", "p1"].map((side, index) => {
        const kind = participantType(match, side);
        const isWinner = winnerSide === (side === "p0" ? "P0" : "P1");
        const isLoser = winnerSide != null && !isWinner;
        return (
          <div key={side}>
            {index === 1 ? (
              <div className="lab-row" style={{ gap: 8, margin: "8px 0" }}>
                <hr className="lab-rule" />
                <span className="lab-mono" style={{ fontSize: 7 }}>VS</span>
                <hr className="lab-rule" />
              </div>
            ) : null}
            <div className="mat-side__player">
              <span className={`lab-avatar${isWinner ? " lab-avatar--lime" : ""}`}>
                {kind === "model" ? <Box size={12} /> : kind === "ai" ? <Bot size={12} /> : <UserRound size={12} />}
              </span>
              <div style={{ minWidth: 0 }}>
                <div className="mat-side__player-name">{names[side]}</div>
                <div className="mat-side__player-sub">
                  {participantSub(match, side)}
                  {typeof score === "number" ? ` · SCORE ${score}` : ""}
                </div>
              </div>
              <span className={`mat-side__score${isWinner ? " is-win" : ""}`}>
                {isWinner ? "W" : isLoser ? "L" : "—"}
              </span>
            </div>
          </div>
        );
      })}
      <hr className="lab-rule" />
      <div className="lab-mono" style={{ fontSize: 8.5 }}>
        {winnerSide ? `${names[winnerSide === "P0" ? "p0" : "p1"]} 获胜` : "平局或无胜者"}
        {result.cause ? ` · ${result.cause}` : ""}
      </div>
      {replay ? (
        <div className="lab-mono" style={{ fontSize: 8 }}>
          SEED {replay.seed ?? "—"} · {(replay.moves || []).length} MOVES · v{replay.game_version || "—"}
        </div>
      ) : null}
    </div>
  );
}

export default function Matches() {
  const { token, user, authReady } = useAuth();
  const { openAuth } = useLabAuth();
  const [params] = useSearchParams();
  const loggedIn = Boolean(user) && user.role !== "guest";
  const query = useMatches(token, Boolean(authReady && loggedIn));
  const [filter, setFilter] = useState("all");
  const [selectedId, setSelectedId] = useState(() => {
    const fromUrl = params.get("match");
    return fromUrl ? Number(fromUrl) : null;
  });
  const [cursor, setCursor] = useState(0);
  const [playing, setPlaying] = useState(false);
  const playTimer = useRef(null);

  const matches = (query.data && query.data.matches) || [];
  const visible = matches.filter((match) => {
    if (filter === "model") return match.kind === "model_vs_model";
    if (filter === "pvp") return match.kind === "pvp";
    if (filter === "running") return isRunning(match);
    return true;
  });
  const selected = matches.find((match) => match.id === selectedId) || visible[0] || matches[0] || null;
  const replayQuery = useMatchReplay(selected && selected.status === "finished" ? selected.id : null);
  const replay = (replayQuery.data && replayQuery.data.replay) || null;
  const moves = (replay && replay.moves) || (selected && Array.isArray(selected.replay) ? selected.replay : []) || [];
  const moveCount = moves.length;
  const current = moves[Math.min(cursor, Math.max(0, moveCount - 1))] || null;

  useEffect(() => {
    setCursor(0);
    setPlaying(false);
  }, [selected && selected.id]);

  useEffect(() => {
    if (!playing) {
      if (playTimer.current) {
        clearInterval(playTimer.current);
        playTimer.current = null;
      }
      return undefined;
    }
    playTimer.current = setInterval(() => {
      setCursor((value) => {
        if (value >= moveCount - 1) {
          setPlaying(false);
          return value;
        }
        return value + 1;
      });
    }, 380);
    return () => {
      clearInterval(playTimer.current);
      playTimer.current = null;
    };
  }, [playing, moveCount]);

  const shareUrl =
    selected && typeof window !== "undefined"
      ? `${window.location.origin}/watch/match/${selected.id}`
      : "";

  const copyShare = async () => {
    try {
      await navigator.clipboard.writeText(shareUrl);
      toast.success("回放链接已复制");
    } catch (e) {
      toast.error("复制失败");
    }
  };

  const downloadReplay = () => {
    if (!replay) return;
    const blob = new Blob([JSON.stringify(replay, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `match-${replay.match_id}-replay.json`;
    link.click();
    URL.revokeObjectURL(url);
  };

  if (!authReady) return <Loading label="连接账号服务" />;

  if (!loggedIn) {
    return (
      <>
        <div className="lab-page-head">
          <div className="lab-page-head__copy">
            <h1 className="lab-h1">对局与回放</h1>
            <p className="lab-subtitle">每场对局自动落库 · 可逐帧回放、分享链接与复盘</p>
          </div>
        </div>
        <div className="lab-card" style={{ padding: 0 }}>
          <EmptyState
            icon={<Swords size={18} />}
            title="登录后查看你的对局记录"
            desc="PvP 与模型对战都会在这里留下回放；分享链接无需登录也能打开。"
            action={
              <Button variant="primary" onClick={() => openAuth("login")}>
                登录
              </Button>
            }
          />
        </div>
      </>
    );
  }

  return (
    <>
      <div className="lab-page-head">
        <div className="lab-page-head__copy">
          <h1 className="lab-h1">对局与回放</h1>
          <p className="lab-subtitle">每场对局自动落库 · 可逐帧回放、分享链接与复盘</p>
        </div>
        <div className="lab-page-head__actions">
          <Button variant="outline" size="sm" onClick={query.reload}>
            <RefreshCw size={13} />
            刷新
          </Button>
          <Link to="/models" className="lab-btn lab-btn--primary lab-btn--sm">
            <Swords size={13} />
            发起对战
          </Link>
        </div>
      </div>

      {query.error ? <ErrorNote error={query.error} onRetry={query.reload} /> : null}

      <div className="mat-layout">
        <div className="mat-col">
          <div className="mat-list">
            <div className="mat-list__head">
              <span className="lab-card__title">MATCHES</span>
              <span className="lab-mono" style={{ fontSize: 8 }}>{matches.length} 场</span>
            </div>
            <div className="mat-list__filters">
              {FILTERS.map((item) => (
                <button
                  key={item.key}
                  type="button"
                  className={`env-filter${filter === item.key ? " is-active" : ""}`}
                  onClick={() => setFilter(item.key)}
                >
                  {item.label}
                </button>
              ))}
            </div>
            <div className="mat-list__body">
              {query.loading && matches.length === 0 ? (
                <Loading label="载入对局" />
              ) : visible.length === 0 ? (
                <EmptyState
                  icon={<Swords size={15} />}
                  title="还没有对局"
                  desc="把模型托管到平台并发起一次挑战，对局完成后回放会出现在这里。"
                  action={
                    <Link className="lab-link lab-link--lime" to="/models">
                      去发起挑战
                      <ArrowRight size={12} />
                    </Link>
                  }
                />
              ) : (
                visible.map((match) => (
                  <button
                    key={match.id}
                    type="button"
                    className={`mat-row${selected && selected.id === match.id ? " is-selected" : ""}`}
                    onClick={() => setSelectedId(match.id)}
                  >
                    <ReplayRow match={match} />
                  </button>
                ))
              )}
            </div>
          </div>
        </div>

        <div className="mat-col">
          <div className="mat-replay">
            {!selected ? (
              <EmptyState
                icon={<Play size={16} />}
                title="选择一场对局"
                desc="左侧选择一场已结束的对局，右侧会加载回放与动作流。"
              />
            ) : (
              <>
                <div className="mat-replay__head">
                  <span className="lab-card__title" style={{ display: "flex", gap: 8, alignItems: "center" }}>
                    REPLAY
                    <span className="lab-chip">#{selected.id}</span>
                  </span>
                  <div className="lab-row" style={{ gap: 8 }}>
                    <Pill tone={statusTone(selected.status)} dot>
                      {statusLabel(selected.status)}
                    </Pill>
                    <span className="lab-mono" style={{ fontSize: 8 }}>{moveCount} MOVES</span>
                  </div>
                </div>

                <div className="mat-scorestrip">
                  {["p0", "p1"].map((side, index) => (
                    <div key={side} style={{ display: "contents" }}>
                      {index === 1 ? <span className="mat-vs">VS</span> : null}
                      <div className="mat-player">
                        <span className={`lab-avatar${outcomeOf(selected) === (side === "p0" ? "P0" : "P1") ? " lab-avatar--lime" : ""}`}>
                          {participantType(selected, side) === "model" ? (
                            <Box size={12} />
                          ) : participantType(selected, side) === "ai" ? (
                            <Bot size={12} />
                          ) : (
                            <UserRound size={12} />
                          )}
                        </span>
                        <div style={{ minWidth: 0 }}>
                          <div className="mat-player__name">{participantName(selected, side)}</div>
                          <div className="mat-player__sub">{participantSub(selected, side)}</div>
                        </div>
                        <span className={`mat-player__score${outcomeOf(selected) === (side === "p0" ? "P0" : "P1") ? " is-win" : ""}`}>
                          {outcomeOf(selected) === (side === "p0" ? "P0" : "P1") ? "1" : "0"}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>

                <div className="mat-replay__body">
                  <div className="mat-board-well">
                    <span className="mat-board-tag">
                      {selected.status === "finished" ? "REPLAY" : "WAITING"}
                    </span>
                    <MiniBoard game={selected.game} size="lg" tag={null} />
                  </div>
                  <div className="mat-log">
                    <div className="mat-log__head">
                      <span className="lab-section-label">ACTION LOG</span>
                      <span className="lab-mono" style={{ fontSize: 7.5 }}>
                        {current ? `TICK ${current.tick}` : "NO MOVES"}
                      </span>
                    </div>
                    <div className="mat-log__body">
                      {moveCount === 0 ? (
                        <span className="lab-subtitle" style={{ fontSize: 11 }}>
                          本局没有动作记录（可能为认输/取消），暂无回放数据。
                        </span>
                      ) : (
                        moves.slice(0, Math.max(cursor + 1, 12)).map((move, index) => (
                          <div
                            className="mat-log__row"
                            key={`${move.tick}-${index}`}
                            style={{ opacity: index <= cursor ? 1 : 0.45 }}
                          >
                            <span className="mat-log__tick">{move.tick}</span>
                            <span className="mat-log__action">{shortAction(move.action)}</span>
                            {move.opponent != null ? (
                              <span className="lab-mono" style={{ fontSize: 7.5, marginLeft: "auto" }}>
                                OPP {shortAction(move.opponent)}
                              </span>
                            ) : null}
                          </div>
                        ))
                      )}
                    </div>
                    {replayQuery.loading ? <Loading label="载入回放" /> : null}
                    {replayQuery.error ? <ErrorNote error={replayQuery.error} onRetry={replayQuery.reload} /> : null}
                  </div>
                </div>

                <div className="mat-controls">
                  <button
                    type="button"
                    className="mat-controls__play"
                    onClick={() => {
                      if (cursor >= moveCount - 1) setCursor(0);
                      setPlaying((value) => !value);
                    }}
                    disabled={moveCount === 0}
                    title={playing ? "暂停" : "播放"}
                  >
                    {playing ? <Pause size={13} /> : <Play size={13} />}
                  </button>
                  <input
                    className="mat-timeline"
                    type="range"
                    min={0}
                    max={Math.max(0, moveCount - 1)}
                    value={Math.min(cursor, Math.max(0, moveCount - 1))}
                    onChange={(event) => {
                      setPlaying(false);
                      setCursor(Number(event.target.value));
                    }}
                    aria-label="回放进度"
                  />
                  <span className="mat-controls__time">
                    {moveCount ? `${cursor + 1} / ${moveCount}` : "0 / 0"}
                  </span>
                  <span className="mat-controls__speed">1×</span>
                </div>
              </>
            )}
          </div>
        </div>

        <aside className="mat-side">
          {selected ? (
            <>
              <Scoreboard match={selected} replay={replay} />
              <div className="lab-card">
                <div className="lab-card__head">
                  <span className="lab-card__title">SHARE</span>
                  <span className="lab-mono" style={{ fontSize: 8 }}>PUBLIC LINK</span>
                </div>
                <div className="mat-share-link">
                  <span>{shareUrl || "/watch/match/—"}</span>
                  <Copy size={10} />
                </div>
                <div className="mat-share-btns">
                  <button type="button" onClick={copyShare} title="复制回放链接">
                    <Copy size={12} />
                  </button>
                  <button type="button" onClick={downloadReplay} disabled={!replay} title="下载回放 JSON">
                    <Download size={12} />
                  </button>
                  <a href={shareUrl || "#"} target="_blank" rel="noreferrer" title="在新窗口打开回放" className="lab-icon-btn lab-icon-btn--bare">
                    <ExternalLink size={12} />
                  </a>
                </div>
                <span className="lab-mono" style={{ fontSize: 7.5 }}>
                  公开回放 · 无需登录即可查看（旧版播放器）
                </span>
              </div>
              <div className="lab-card">
                <div className="lab-card__head">
                  <span className="lab-card__title">MATCH INFO</span>
                  <Trophy size={12} style={{ color: "var(--lab-text-3)" }} />
                </div>
                {[
                  ["对局 ID", `#${selected.id}`],
                  ["游戏", gameLabel(selected.game)],
                  ["类型", kindLabel(selected.kind)],
                  ["模式", (selected.result && selected.result.mode) || "—"],
                  ["步数", moveCount || "—"],
                  ["创建时间", relativeTime(selected.created_at)],
                ].map(([label, value]) => (
                  <div className="lab-meta-row" key={label}>
                    <span>{label}</span>
                    <b>{value}</b>
                  </div>
                ))}
                <hr className="lab-rule" />
                <a className="lab-btn lab-btn--outline lab-btn--sm lab-btn--block" href={shareUrl || "#"} target="_blank" rel="noreferrer">
                  <Play size={12} />
                  在新窗口播放回放
                </a>
              </div>
            </>
          ) : (
            <div className="lab-card">
              <EmptyState icon={<Swords size={16} />} title="暂无选中对局" />
            </div>
          )}
        </aside>
      </div>
    </>
  );
}
