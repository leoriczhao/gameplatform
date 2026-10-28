import { useState } from "react";
import { Link } from "react-router-dom";
import {
  ArrowRight,
  Bot,
  Box,
  ExternalLink,
  RefreshCw,
  Swords,
  Trophy,
  UserRound,
} from "lucide-react";
import { useAuth } from "../../AuthContext.jsx";
import { useLabAuth } from "../AuthDialog.jsx";
import { useMatches } from "../api.js";
import { Button, EmptyState, ErrorNote, Loading, Pill } from "../ui.jsx";
import {
  gameColor,
  gameLabel,
  kindLabel,
  participantName,
  participantSub,
  participantType,
  relativeTime,
} from "../format.js";

const FILTERS = [
  { key: "all", label: "全部" },
  { key: "model", label: "模型对战" },
  { key: "pvp", label: "PvP" },
  { key: "running", label: "进行中" },
];

// v2 记录的状态是 waiting/active/finished/aborted/cancelled；v1 老记录是
// running/queued/finished。两边都算"进行中"，列表里无需区分新旧。
const LIVE_STATUS = new Set(["running", "queued", "waiting", "active"]);

function isRunning(match) {
  return LIVE_STATUS.has(match.status);
}

function statusLabel(status) {
  const map = {
    finished: "已结束",
    running: "进行中",
    active: "进行中",
    queued: "排队中",
    waiting: "等待对手",
    aborted: "已中止",
    cancelled: "已取消",
  };
  return map[status] || status || "—";
}

function statusTone(status) {
  if (status === "finished") return "green";
  if (status === "aborted" || status === "cancelled") return "red";
  if (isRunning(status)) return "amber";
  return "neutral";
}

// v1 记录 winner 是 0/1，v2 记录 winner 是 "p0"/"p1"；两种都归一成 P0/P1。
function winnerSide(match) {
  const winner = match && match.result && match.result.winner;
  if (winner === 0 || winner === "p0") return "P0";
  if (winner === 1 || winner === "p1") return "P1";
  return null;
}

function MatchRow({ match }) {
  const uid = match.uid;
  const winner = winnerSide(match);
  const cause = match.result && match.result.cause;
  const body = (
    <>
      <div className="mat-row__top">
        <span className="mat-row__id">
          {uid ? `#${String(uid).slice(0, 8)}` : `#${match.id}`}
        </span>
        <div className="lab-row" style={{ gap: 7 }}>
          {winner ? (
            <Pill tone={winner === "P0" ? "green" : "red"} dot>
              {winner} WIN
            </Pill>
          ) : cause ? (
            <Pill tone="neutral">{String(cause).toUpperCase()}</Pill>
          ) : null}
          <span className="lab-mono" style={{ fontSize: 7.5 }}>
            {relativeTime(match.created_at)}
          </span>
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
        <div className="lab-row" style={{ gap: 6 }}>
          <Pill tone={statusTone(match.status)}>{statusLabel(match.status)}</Pill>
          {uid ? <ExternalLink size={11} color="var(--lab-text-3)" /> : null}
        </div>
      </div>
    </>
  );
  // 旧 v1 记录没有 uid，无法定位到 /m/:id（等 M4 数据迁移后再统一）
  if (!uid) {
    return (
      <div className="mat-row" title="旧对局没有舞台 id，暂时无法打开回放">
        {body}
      </div>
    );
  }
  return (
    <Link className="mat-row" to={`/m/${uid}`}>
      {body}
    </Link>
  );
}

function ScoreLine({ match }) {
  const winner = winnerSide(match);
  const score = match.result && match.result.score;
  return (
    <div className="lab-card" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <div className="lab-card__head">
        <span className="lab-card__title">MATCH INFO</span>
        <Trophy size={12} style={{ color: "var(--lab-text-3)" }} />
      </div>
      {["p0", "p1"].map((side) => {
        const kind = participantType(match, side);
        const isWinner = winner === (side === "p0" ? "P0" : "P1");
        return (
          <div className="mat-side__player" key={side}>
            <span className={`lab-avatar${isWinner ? " lab-avatar--lime" : ""}`}>
              {kind === "model" ? (
                <Box size={12} />
              ) : kind === "ai" ? (
                <Bot size={12} />
              ) : (
                <UserRound size={12} />
              )}
            </span>
            <div style={{ minWidth: 0 }}>
              <div className="mat-side__player-name">{participantName(match, side)}</div>
              <div className="mat-side__player-sub">
                {participantSub(match, side)}
                {typeof score === "number" ? ` · SCORE ${score}` : ""}
              </div>
            </div>
            <span className={`mat-side__score${isWinner ? " is-win" : ""}`}>
              {isWinner ? "W" : winner ? "L" : "—"}
            </span>
          </div>
        );
      })}
      <hr className="lab-rule" />
      <div className="lab-mono" style={{ fontSize: 8.5 }}>
        {winner
          ? `${participantName(match, winner === "P0" ? "p0" : "p1")} 获胜`
          : "平局或无胜者"}
        {match.result && match.result.cause ? ` · ${match.result.cause}` : ""}
      </div>
      <div className="lab-mono" style={{ fontSize: 8 }}>
        {match.uid ? `UID ${match.uid}` : `ID ${match.id}`} ·{" "}
        {relativeTime(match.created_at)}
      </div>
    </div>
  );
}

export default function Matches() {
  const { token, user, authReady } = useAuth();
  const { openAuth } = useLabAuth();
  const loggedIn = Boolean(user) && user.role !== "guest";
  const query = useMatches(token, Boolean(authReady && loggedIn));
  const [filter, setFilter] = useState("all");

  const matches = (query.data && query.data.matches) || [];
  const visible = matches.filter((match) => {
    if (filter === "model") return match.kind === "model_vs_model";
    if (filter === "pvp") return match.kind === "pvp";
    if (filter === "running") return isRunning(match);
    return true;
  });
  const selected = visible[0] || matches[0] || null;
  const liveCount = matches.filter(isRunning).length;

  if (!authReady) return <Loading label="连接账号服务" />;

  if (!loggedIn) {
    return (
      <>
        <div className="lab-page-head">
          <div className="lab-page-head__copy">
            <h1 className="lab-h1">对局记录</h1>
            <p className="lab-subtitle">登录后查看对局记录 · 回放与直播统一在 /m/:id 舞台查看</p>
          </div>
        </div>
        <div className="lab-card" style={{ padding: 0 }}>
          <EmptyState
            icon={<Swords size={18} />}
            title="登录后查看你的对局记录"
            desc="练习局、PvP 与模型对战都会落库；每场对局都可以在舞台里回放或分享。"
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
          <h1 className="lab-h1">对局记录</h1>
          <p className="lab-subtitle">
            每场对局自动落库 · 点击对局进入 /m/:id 舞台，直播、逐帧回放与分享都在那里
          </p>
        </div>
        <div className="lab-page-head__actions">
          <Button variant="outline" size="sm" onClick={query.reload}>
            <RefreshCw size={13} />
            刷新
          </Button>
          <Link to="/models" className="lab-btn lab-btn--primary lab-btn--sm">
            <Swords size={13} />
            发起模型对战
          </Link>
        </div>
      </div>

      {query.error ? <ErrorNote error={query.error} onRetry={query.reload} /> : null}

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "minmax(0, 1fr) 340px",
          gap: 18,
          alignItems: "start",
        }}
      >
        <div className="mat-list">
          <div className="mat-list__head">
            <span className="lab-card__title">MATCHES</span>
            <span className="lab-mono" style={{ fontSize: 8 }}>
              {matches.length} 场 · {liveCount} 进行中
            </span>
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
                desc="去游戏页开始一局练习，或在大厅约战；结束后记录会出现在这里。"
                action={
                  <Link className="lab-link lab-link--lime" to="/environments">
                    去挑一个环境
                    <ArrowRight size={12} />
                  </Link>
                }
              />
            ) : (
              visible.map((match) => <MatchRow match={match} key={match.id} />)
            )}
          </div>
        </div>

        <aside className="mat-side">
          {selected ? <ScoreLine match={selected} /> : null}

          <div className="lab-card" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <div className="lab-card__head">
              <span className="lab-card__title">STAGE</span>
              <ExternalLink size={12} style={{ color: "var(--lab-text-3)" }} />
            </div>
            <span className="lab-subtitle" style={{ fontSize: 11, lineHeight: 1.65 }}>
              回放不再使用旧版播放器：所有对局（直播 / 回放 / 分享）统一打开
              <span className="lab-mono"> /m/&lt;uid&gt; </span>
              舞台，逐帧来自 <span className="lab-mono">/api/v2/matches/&#123;id&#125;/frames</span>。
            </span>
            <Link
              className="lab-btn lab-btn--outline lab-btn--sm"
              to="/environments"
              style={{ justifyContent: "center" }}
            >
              <Swords size={12} />
              开始新对局
            </Link>
          </div>

          <div className="lab-card" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <div className="lab-card__head">
              <span className="lab-card__title">模型对战</span>
              <Box size={12} style={{ color: "var(--lab-text-3)" }} />
            </div>
            <span className="lab-subtitle" style={{ fontSize: 11, lineHeight: 1.65 }}>
              模型 vs 模型由两个 model 座位组成，与练习局、PvP 走同一条对局时间线。
            </span>
            <Link className="lab-btn lab-btn--ghost lab-btn--sm" to="/models">
              去模型工作台
              <ArrowRight size={12} />
            </Link>
          </div>
        </aside>
      </div>
    </>
  );
}
