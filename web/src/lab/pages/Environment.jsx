import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { toast } from "sonner";
import {
  ArrowRight,
  BookOpen,
  Check,
  Download,
  ExternalLink,
  Play,
  RotateCcw,
  Swords,
  Terminal,
  Trophy,
  Users,
} from "lucide-react";
import { useAuth } from "../../AuthContext.jsx";
import { useGames, useLeaderboard, post } from "../api.js";
import { useLabAuth } from "../AuthDialog.jsx";
import { contractRows, FALLBACK_GAMES, normalizeGame } from "../games.js";
import MiniBoard from "../MiniBoard.jsx";
import Stage from "../../stage/Stage.jsx";
import {
  Button,
  Chip,
  CopyButton,
  EmptyState,
  ErrorNote,
  LinkButton,
  Loading,
  Pill,
  Tabs,
} from "../ui.jsx";


const KEY_GLYPH = {
  ArrowLeft: "←",
  ArrowRight: "→",
  ArrowUp: "↑",
  ArrowDown: "↓",
  Space: "SPACE",
  " ": "SPACE",
};

function actionList(game) {
  const keys = (game.meta && game.meta.controls && game.meta.controls.keys) || null;
  if (keys && typeof keys === "object") {
    return Object.entries(keys).slice(0, 4).map(([key, value]) => ({
      key,
      displayKey: KEY_GLYPH[key] || (/^[a-zA-Z]$/.test(key) ? key.toUpperCase() : key),
      code: Array.isArray(value) ? value[0] : value,
      label: Array.isArray(value) ? value[1] : String(key),
    }));
  }
  const out = (game.contract && game.contract.out_shape) || [];
  const count = out.length ? Number(out[out.length - 1]) || 0 : 0;
  return Array.from({ length: Math.min(4, count) }, (_, index) => ({
    key: String(index),
    displayKey: String(index),
    code: index,
    label: `动作 ${index}`,
  }));
}

function PreviewPanel({ game }) {
  const actions = actionList(game);
  const scoreLabel = game.board ? `${game.board.width}×${game.board.height}` : "—";
  return (
    <div className="envp-preview">
      <div className="envp-preview__head">
        <span className="envp-preview__live">
          <i aria-hidden="true" /> LIVE PREVIEW
        </span>
        <span className="lab-mono" style={{ fontSize: 8 }}>
          {game.en} · {game.version ? `v${game.version}` : "LOCAL"}
        </span>
      </div>
      <div className="envp-board-wrap">
        <div className="envp-board">
          <MiniBoard game={game.id} size="lg" tag={null} />
        </div>
        <div className="envp-hud">
          <div className="envp-next">
            <div>
              <div className="envp-next__label">NEXT</div>
              <div className="envp-next__box">
                <div className="envp-next__cells">
                  <i /><i /><i /><i />
                </div>
              </div>
            </div>
            <div className="envp-action-chip">
              <span className="envp-next__label">ACTION</span>
              <span
              className="lab-mono"
              style={{ color: "var(--lab-lime-text)", fontSize: 10, whiteSpace: "nowrap" }}
            >
              {actions[0] ? `${actions[0].code} · ${actions[0].label}` : "—"}
            </span>
            </div>
          </div>
          <div className="envp-hud-stat">
            <span>SCORE</span>
            <b>0</b>
          </div>
          <div className="envp-hud-stat">
            <span>STEPS</span>
            <b>0</b>
          </div>
          <div className="envp-hud-stat">
            <span>BOARD</span>
            <b style={{ fontSize: 15 }}>{scoreLabel}</b>
          </div>
          <hr className="lab-rule" />
          <div className="envp-keys">
            {actions.map((action) => (
              <div className="envp-keys__row" key={action.key}>
                <span className="envp-keycap">{action.displayKey}</span>
                {action.label}
              </div>
            ))}
          </div>
        </div>
      </div>
      <div className="envp-preview__btns">
        <LinkButton variant="primary" href={game.pageUrl} className="lab-grow">
          <Play size={13} />
          开始试玩
        </LinkButton>
        <span className="lab-icon-btn" aria-hidden="true">
          <RotateCcw size={14} />
        </span>
      </div>
      <span className="lab-mono" style={{ fontSize: 8, letterSpacing: "0.03em" }}>
        试玩页由旧版会话引擎提供 · 用于核对动力学与规则
      </span>
    </div>
  );
}

function ContractCard({ game, compact = false }) {
  const rows = contractRows(game);
  const actions = actionList(game);
  const hasContract = Boolean(game.contract);
  return (
    <div className="lab-card" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div className="lab-card__head">
        <span className="lab-card__title">CONTRACT</span>
        <Pill tone={hasContract ? "green" : "amber"} dot>
          {hasContract ? "DECLARED" : "MISSING"}
        </Pill>
      </div>
      <span className="lab-section-label">OBSERVATION</span>
      {rows.length === 0 ? (
        <span className="lab-subtitle">该游戏未声明模型观测契约。</span>
      ) : (
        rows.map((row) => (
          <div className="envp-obs-row" key={row.name}>
            <span className="envp-obs-row__name">
              <i aria-hidden="true" />
              {row.name}
            </span>
            <span className="envp-obs-row__meta">
              <span>{row.type}</span>
              <b>{row.shape}</b>
            </span>
          </div>
        ))
      )}
      <hr className="lab-rule" />
      <span className="lab-section-label">ACTION SPACE</span>
      <div className="envp-act-grid">
        {actions.map((action) => (
          <span className="envp-act" key={action.key}>
            <span>{action.displayKey}</span>
            {action.label}
          </span>
        ))}
      </div>
      <div className="envp-schema">
        {game.contract
          ? `{ "in_shape": ${JSON.stringify(game.contract.in_shape || [])}, "out_shape": ${JSON.stringify(game.contract.out_shape || [])} }`
          : "// 无模型契约：仅支持人工/内置 AI 对战"}
      </div>
      <div className="envp-valid">
        <Check size={12} />
        {hasContract ? "契约形状由服务端校验 · 上传时强制检查" : "上传 ONNX 前需要游戏作者声明契约"}
      </div>
      <div className="lab-row" style={{ gap: 8 }}>
        <LinkButton size="sm" variant="outline" href={game.schemaUrl} target="_blank" rel="noreferrer">
          <Download size={12} />
          契约 JSON
        </LinkButton>
        {!compact ? (
          <a className="lab-btn lab-btn--ghost lab-btn--sm" href="/api.html" target="_blank" rel="noreferrer">
            接入文档
            <ExternalLink size={11} />
          </a>
        ) : null}
      </div>
    </div>
  );
}

function RenderCard({ game }) {
  const board = game.board || {};
  const cell = board.cell || {};
  const palette = board.palette ? Object.keys(board.palette).length : 0;
  const hud = Array.isArray(board.hud) ? board.hud.length : 0;
  const events = Array.isArray(board.events) ? board.events.length : 0;
  return (
    <div className="lab-card" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <div className="lab-card__head">
        <span className="lab-card__title">RENDER V2</span>
        <span className="lab-mono" style={{ fontSize: 8, color: "var(--lab-cyan)" }}>
          DECLARATIVE
        </span>
      </div>
      <div className="lab-meta-row">
        <span>board</span>
        <b>
          {board.width || "?"} × {board.height || "?"}
          {cell.size ? ` · cell ${cell.size}` : ""}
        </b>
      </div>
      <div className="lab-meta-row">
        <span>palette</span>
        <b>{palette ? `${palette} 种状态` : "默认"}</b>
      </div>
      <div className="lab-meta-row">
        <span>hud / events</span>
        <b>
          {hud} / {events}
        </b>
      </div>
      <div className="lab-meta-row">
        <span>资产</span>
        <b>{game.meta && game.meta.assets ? Object.keys(game.meta.assets).length : 0} 个文件</b>
      </div>
      <hr className="lab-rule" />
      <span className="lab-subtitle" style={{ fontSize: 10, lineHeight: 1.55 }}>
        在 game.yaml 声明棋盘、精灵与 HUD，平台通用渲染层负责表现。
      </span>
    </div>
  );
}

function EndpointCard({ game }) {
  return (
    <div className="lab-card" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <div className="lab-card__head">
        <span className="lab-card__title">OPENENV ENDPOINT</span>
        <span className="lab-mono" style={{ fontSize: 7.5, color: "var(--lab-green)" }}>
          WS · STREAMING
        </span>
      </div>
      <div className="envp-url">
        <span>{game.openenvUrl}</span>
        <CopyButton text={game.openenvUrl} />
      </div>
      <span className="lab-mono" style={{ fontSize: 8.5 }}>GenericEnvClient(base_url=…).sync()</span>
      <div className="lab-row" style={{ gap: 8 }}>
        <LinkButton size="sm" variant="outline" className="lab-grow" href={game.schemaUrl} target="_blank" rel="noreferrer">
          <Download size={11} />
          契约 JSON
        </LinkButton>
        <a className="lab-icon-btn" href={game.pageUrl} title="打开试玩页">
          <ExternalLink size={12} />
        </a>
      </div>
    </div>
  );
}

function OpponentsCard({ game }) {
  return (
    <div className="lab-card" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <div className="lab-card__head">
        <span className="lab-card__title">OPPONENTS</span>
        <span className="lab-mono" style={{ fontSize: 8 }}>
          {game.hasAi ? "AI" : ""} {game.pvp ? "PVP" : ""}
        </span>
      </div>
      {game.hasAi ? (
        <div className="envp-opp">
          <span>内置基线 AI</span>
          <span className="envp-opp__tag">BOT</span>
        </div>
      ) : null}
      {game.pvp ? (
        <div className="envp-opp">
          <span>真人 PvP（ELO）</span>
          <span className="envp-opp__tag">HUMAN</span>
        </div>
      ) : null}
      {game.contract ? (
        <div className="envp-opp">
          <span>托管 ONNX 模型</span>
          <span className="envp-opp__tag is-model">MODEL</span>
        </div>
      ) : null}
      <hr className="lab-rule" />
      <Link className="lab-link lab-link--lime" to="/models">
        用模型发起挑战
        <ArrowRight size={12} />
      </Link>
    </div>
  );
}

function LeaderboardCard({ game }) {
  const { token, user, authReady } = useAuth();
  const { openAuth } = useLabAuth();
  const loggedIn = Boolean(user) && user.role !== "guest";
  const query = useLeaderboard(game.id, token, Boolean(authReady && loggedIn));
  const items = (query.data && query.data.items) || [];
  return (
    <div className="lab-card" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <div className="lab-card__head">
        <span className="lab-card__title">LEADERBOARD</span>
        <span className="lab-mono" style={{ fontSize: 8 }}>总榜 ELO</span>
      </div>
      {!loggedIn ? (
        <EmptyState
          icon={<Trophy size={15} />}
          title="登录后查看排行榜"
          desc="ELO 总榜按游戏分别统计。"
          action={
            <Button size="sm" variant="primary" onClick={() => openAuth("login")}>
              登录
            </Button>
          }
        />
      ) : query.loading ? (
        <Loading label="载入排行榜" />
      ) : query.error ? (
        <ErrorNote error={query.error} onRetry={query.reload} />
      ) : items.length === 0 ? (
        <EmptyState icon={<Users size={15} />} title="榜单还是空的" desc="完成一场 PvP 后就会出现 ELO 记录。" />
      ) : (
        items.slice(0, 5).map((item, index) => (
          <div className="envp-lb-row" key={item.user_id || item.name}>
            <span className={`envp-lb-row__rank${index === 0 ? " is-top" : ""}`}>
              {String(index + 1).padStart(2, "0")}
            </span>
            <span className="lab-truncate" style={{ maxWidth: 150 }}>{item.name}</span>
            <span className="envp-lb-row__score">{Math.round(item.rating)}</span>
          </div>
        ))
      )}
    </div>
  );
}

function SessionLog() {
  const rows = [
    ["0128", "旋转 · 消 2 行", "+2"],
    ["0124", "右移 · 继续下落", "0"],
    ["0119", "左移 · 边缘寻位", "0"],
    ["0112", "旋转 · T-Spin 位", "0"],
  ];
  return (
    <div className="envp-log">
      <div className="lab-card__head">
        <span className="lab-card__title">SESSION LOG</span>
        <span className="lab-mono" style={{ fontSize: 8 }}>STEP 128</span>
      </div>
      {rows.map(([tick, action, delta]) => (
        <div className="envp-log__row" key={tick}>
          <span className="envp-log__tick">{tick}</span>
          {action}
          <span className={`envp-log__delta${delta !== "0" ? " is-up" : ""}`}>{delta}</span>
        </div>
      ))}
      <span className="lab-mono" style={{ fontSize: 8 }}>试玩页开始一局后，这里会同步动作流</span>
    </div>
  );
}

// 试玩 tab 创建练习局的失败码 → 人话（docs/design/17 §5.1：错误带机器可读的 code）
const PLAY_ERROR_TEXT = {
  bad_controller: "AI 策略不可用，请刷新后再试",
  bad_seats: "座位配置与服务端不一致，请刷新后再试",
  bad_mode: "练习模式暂不可用",
  bad_visibility: "可见性设置不受支持",
  bad_settings: "开局失败，请稍后再试",
  unknown_game: "游戏不存在或未公开",
  too_many_matches: "同时进行的对局过多，请先结束其它对局",
  login_required: "请先登录",
};

function playErrorText(error) {
  if (!error) return "创建试玩对局失败";
  return (error.code && PLAY_ERROR_TEXT[error.code]) || error.message || "创建试玩对局失败";
}

/* 试玩 tab：内嵌 v2 舞台（设计 17 §7.7）。
   旧 PreviewPanel + 假 SessionLog 不再承担试玩，这里只负责
   「登录 → POST /api/v2/matches 创建 practice 对局 → <Stage uid variant="embedded">」。 */
function PlayTab({ game, matchId, onMatchIdChange }) {
  const { user, token, authReady } = useAuth();
  const { openAuth } = useLabAuth();
  const loggedIn = Boolean(user) && user.role !== "guest";
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState(null);
  // 创建请求返回前组件可能已卸载（切 tab / 离开页面），用 ref 挡住 setState
  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const meta = game.meta || {};
  // 座位数与服务端 match_engine.seat_count() 保持一致：game.yaml 的 seats 优先，
  // 否则只有声明了 PvP / 内置对手的游戏才是 2 座（ai_strategies 不占第二个座位）。
  const seatCount = useMemo(() => {
    const declared = Number(meta.seats) || 0;
    if (declared) return declared;
    const hasPvp = game.pvp || Boolean(meta.pvp && meta.pvp.enabled)
      || (Array.isArray(meta.opponents) && meta.opponents.length > 0);
    return hasPvp ? 2 : 1;
  }, [game.pvp, meta.seats, meta.pvp, meta.opponents]);

  // AI 策略：opponents 与 ai_strategies 合并，和 match_engine._checked_controller 同口径
  const strategies = useMemo(() => {
    const raw = [...(meta.opponents || []), ...(meta.ai_strategies || [])];
    return [...new Set(raw.map(String).filter(Boolean))];
  }, [meta.opponents, meta.ai_strategies]);

  // 2 座却没有内置 AI：单机练习凑不齐两个座位，只能去 PvP 大厅约真人
  const needsHumanOpponent = seatCount >= 2 && strategies.length === 0;
  const pvpPath = `/games/${game.id}/pvp`;

  const start = async () => {
    if (!loggedIn) {
      openAuth("login");
      return;
    }
    if (needsHumanOpponent) return;
    const seats = [{ seat: "p0", occupant: "me", controller: { type: "human" } }];
    if (seatCount >= 2) {
      seats.push({
        seat: "p1",
        occupant: null,
        controller: { type: "ai", strategy: strategies[0] },
      });
    }
    const body = { game: game.id, seats, mode: "practice", visibility: "unlisted" };
    setCreating(true);
    setError(null);
    try {
      const view = await post("/api/v2/matches", body, token);
      if (!mountedRef.current) return;
      if (!view || !view.id) throw new Error("服务端没有返回对局 id");
      onMatchIdChange(view.id);
    } catch (e) {
      if (!mountedRef.current) return;
      const text = playErrorText(e);
      setError({ message: text, code: e && e.code });
      if (e && (e.code === "login_required" || e.status === 401)) {
        openAuth("login");
      } else {
        toast.error(text);
      }
    } finally {
      if (mountedRef.current) setCreating(false);
    }
  };

  // 「换一局」先重置 matchId；练习局不会自动结束，顺手认输旧局避免占用并发额度
  const restart = () => {
    const oldId = matchId;
    onMatchIdChange(null);
    setError(null);
    if (oldId) {
      post(`/api/v2/matches/${oldId}/resign`, {}, token).catch(() => {});
    }
  };

  if (!authReady) return <Loading label="连接账号服务" />;

  if (!loggedIn) {
    return (
      <div className="lab-card">
        <EmptyState
          icon={<Play size={17} />}
          title="登录后开始试玩"
          desc="试玩使用 v2 对局舞台：创建一局 practice 对局后，内嵌的舞台会实时显示帧、操作与时间线。"
          action={
            <Button variant="primary" onClick={() => openAuth("login")}>
              登录 / 注册
            </Button>
          }
        />
      </div>
    );
  }

  if (matchId) {
    return (
      <div className="envp-stage">
        <div className="envp-stage__bar">
          <span className="envp-stage__title">
            <Play size={13} />
            试玩舞台
          </span>
          <span className="envp-stage__id">#{String(matchId).slice(0, 8)}</span>
          <Pill tone="green" dot>LIVE</Pill>
          <span className="envp-stage__hint">
            内嵌舞台与 <span className="lab-mono">/m/{matchId}</span> 是同一局
          </span>
          <div className="envp-stage__actions">
            <Button size="sm" variant="outline" onClick={restart}>
              <RotateCcw size={12} />
              换一局
            </Button>
            <LinkButton size="sm" variant="primary" href={`/m/${matchId}`}>
              <ExternalLink size={12} />
              在舞台页打开
            </LinkButton>
          </div>
        </div>
        {error ? <ErrorNote error={error} /> : null}
        <div className="envp-stage__embed">
          <Stage uid={matchId} variant="embedded" />
        </div>
      </div>
    );
  }

  return (
    <div className="lab-card envp-stage__intro">
      <div className="lab-card__head">
        <span className="lab-card__title">PLAYGROUND · V2 STAGE</span>
        <Pill tone="neutral" dot>PRACTICE</Pill>
      </div>

      {needsHumanOpponent ? (
        <>
          <span className="lab-subtitle" style={{ fontSize: 11.5, lineHeight: 1.7 }}>
            该环境有 {seatCount} 个座位，但没有内置 AI 策略，单机试玩凑不齐对手。
            请到 PvP 大厅创建房间或快速匹配，和真人开局。
          </span>
          <div className="lab-row" style={{ gap: 8 }}>
            <LinkButton variant="primary" size="sm" href={pvpPath}>
              <Swords size={13} />
              去 PvP 大厅
            </LinkButton>
            <span className="lab-mono" style={{ fontSize: 8 }}>{pvpPath}</span>
          </div>
        </>
      ) : (
        <>
          <span className="lab-subtitle" style={{ fontSize: 11.5, lineHeight: 1.7 }}>
            试玩会创建一局 v2 练习对局（practice · unlisted），内嵌的就是
            <span className="lab-mono"> /m/:id </span>
            的正式舞台：实时帧、操作、时间线走同一套协议。
          </span>
          <div className="envp-stage__facts">
            <span>座位 {seatCount}</span>
            <span>对手 {seatCount >= 2 ? `内置 AI · ${strategies[0]}` : "无（单座）"}</span>
            <span>模式 practice · unlisted</span>
          </div>
          {error ? <ErrorNote error={error} /> : null}
          <div className="lab-row" style={{ gap: 8, flexWrap: "wrap" }}>
            <Button variant="primary" size="sm" onClick={start} disabled={creating}>
              <Play size={13} />
              {creating ? "创建对局…" : "开始试玩"}
            </Button>
            {game.pvp ? (
              <LinkButton variant="outline" size="sm" href={pvpPath}>
                <Swords size={12} />
                真人 PvP
              </LinkButton>
            ) : null}
            <LinkButton variant="outline" size="sm" href="/models">
              <ArrowRight size={12} />
              去托管模型
            </LinkButton>
          </div>
          <span className="lab-mono" style={{ fontSize: 8 }}>
            POST /api/v2/matches → Stage uid variant=embedded
          </span>
        </>
      )}
    </div>
  );
}

export default function Environment() {
  const { slug } = useParams();
  const query = useGames();
  const [tab, setTab] = useState("overview");
  // 试玩的当前对局提升到页面级：切到其它 tab 再回来仍接着同一局（舞台靠快照重连），
  // 也避免反复切 tab 重复创建练习局；换环境时 gameId 不匹配，自动回到"未开局"。
  const [playMatch, setPlayMatch] = useState(null);
  const games = (query.data && query.data.games) || [];
  const useFallback = !query.loading && games.length === 0;
  const list = useMemo(
    () => (useFallback ? FALLBACK_GAMES : games).map((game, index) => normalizeGame(game, index)),
    [games, useFallback],
  );
  const game = list.find((item) => item.id === slug || item.name === slug);
  const playMatchId =
    playMatch && game && playMatch.gameId === game.id ? playMatch.id : null;

  if (query.loading) {
    return <Loading label="载入环境" />;
  }
  if (!game) {
    return (
      <div className="lab-card">
        <EmptyState
          icon={<Terminal size={16} />}
          title="没有找到这个环境"
          desc="链接可能已失效，或者该游戏包尚未发布。"
          action={
            <Link className="lab-btn lab-btn--primary lab-btn--sm" to="/environments">
              返回环境目录
            </Link>
          }
        />
      </div>
    );
  }

  return (
    <>
      <div className="envp-title-row">
        <div className="envp-title-left">
          <div className="envp-name-row">
            <h1 className="lab-h1" style={{ fontSize: 33 }}>{game.name}</h1>
            <Chip>{game.en}</Chip>
            {game.version ? <Chip>v{game.version}</Chip> : null}
            <Pill tone={game.contract ? "green" : "amber"} dot>
              {game.contract ? "契约已声明" : "无模型契约"}
            </Pill>
          </div>
          <p className="lab-subtitle">
            {game.board ? `${game.board.width}×${game.board.height} 棋盘` : "环境"}
            {game.hasAi ? " · 内置基线 AI" : ""}
            {game.pvp ? " · PvP 已开放" : ""}
            {game.author ? ` · 作者 ${game.author}` : " · 官方种子"}
          </p>
        </div>
        <div className="lab-page-head__actions">
          <a className="lab-btn lab-btn--outline lab-btn--sm" href="/api.html" target="_blank" rel="noreferrer">
            <BookOpen size={13} />
            在 SDK 中打开
          </a>
          <Button variant="primary" size="sm" onClick={() => setTab("play")}>
            <Play size={13} />
            开始试玩
          </Button>
        </div>
      </div>

      <Tabs
        items={[
          { key: "overview", label: "概览" },
          { key: "contract", label: "契约" },
          { key: "play", label: "试玩" },
          { key: "leaderboard", label: "排行榜" },
        ]}
        value={tab}
        onChange={setTab}
      />

      {tab === "leaderboard" ? (
        <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) 360px", gap: 18, alignItems: "start" }}>
          <ContractCard game={game} compact />
          <LeaderboardCard game={game} />
        </div>
      ) : tab === "contract" ? (
        <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1.1fr) minmax(0, 0.9fr)", gap: 18, alignItems: "start" }}>
          <ContractCard game={game} />
          <div className="envp-col">
            <RenderCard game={game} />
            <EndpointCard game={game} />
          </div>
        </div>
      ) : tab === "play" ? (
        <PlayTab
          game={game}
          matchId={playMatchId}
          onMatchIdChange={(id) => setPlayMatch(id ? { gameId: game.id, id } : null)}
        />
      ) : (
        <div className="envp-layout">
          <div className="envp-col">
            <PreviewPanel game={game} />
            <SessionLog />
          </div>
          <div className="envp-col">
            <ContractCard game={game} />
            <RenderCard game={game} />
          </div>
          <div className="envp-col">
            <EndpointCard game={game} />
            <OpponentsCard game={game} />
            <LeaderboardCard game={game} />
          </div>
        </div>
      )}
    </>
  );
}
