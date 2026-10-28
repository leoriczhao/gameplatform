import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import "./play.css";
import { toast } from "sonner";
import {
  ArrowLeft,
  Bot,
  Box,
  Gamepad2,
  Play as PlayIcon,
  Swords,
  Trophy,
  Users,
} from "lucide-react";
import { useAuth } from "../../AuthContext.jsx";
import { useLabAuth } from "../AuthDialog.jsx";
import { post, useGames, useLeaderboard, useModels } from "../api.js";
import MiniBoard from "../MiniBoard.jsx";
import {
  Button,
  Chip,
  EmptyState,
  ErrorNote,
  Field,
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

// v2 命令的错误带机器可读的 code（docs/design/17 §5.1）。这里把可预期的
// 创建失败翻译成人话；未知错误再退回 error.message。
const CODE_TEXT = {
  bad_controller: "对手配置无效，请重新选择",
  bad_seats: "座位配置无效，请重新选择对手",
  bad_mode: "该模式不可用（单机练习只能用 practice）",
  bad_visibility: "可见性不可用",
  bad_settings: "对局设置无效，请检查 seed",
  unknown_game: "游戏不存在或未公开",
  no_pvp: "该游戏不支持人类对战",
  too_many_matches: "同时进行的对局过多，请先结束其他对局",
  login_required: "请先登录",
};

function errorText(error, fallback = "开始对局失败") {
  if (!error) return fallback;
  return (error.code && CODE_TEXT[error.code]) || error.message || fallback;
}

// 把 game.yaml 的 controls.keys 压成一行提示（和旧试玩页一致的取法）
function controlHints(controls) {
  const keys = controls && controls.keys;
  if (!keys || typeof keys !== "object") return [];
  return Object.entries(keys)
    .slice(0, 6)
    .map(([key, value]) => ({
      key: KEY_GLYPH[key] || key,
      label: Array.isArray(value) ? value[1] : String(key),
    }));
}

export default function Play() {
  const { slug } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const { user, token, authReady } = useAuth();
  const { openAuth } = useLabAuth();

  const gamesQuery = useGames();
  const loggedIn = Boolean(user) && user.role !== "guest";
  const modelsQuery = useModels(token, Boolean(authReady && loggedIn));
  const leaderboardQuery = useLeaderboard(slug, token, true);

  const [choice, setChoice] = useState("solo"); // 单座默认自己玩；双座会回退到 options[0]
  const [strategy, setStrategy] = useState("");
  const [modelId, setModelId] = useState("");
  const [seed, setSeed] = useState("");
  const [creating, setCreating] = useState(false);

  // 组件卸载后不再 setState / toast（导航发生在请求返回之后）
  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const isUgc = location.pathname.startsWith("/games/ugc/");
  const pvpPath = isUgc ? `/games/ugc/${slug}/pvp` : `/games/${slug}/pvp`;

  const catalog = (gamesQuery.data && gamesQuery.data.games) || [];
  const game = catalog.find((item) => item.id === slug) || null;
  const meta = (game && game.meta) || {};
  const board = meta.board || null;
  const hud = Array.isArray(board && board.hud) ? board.hud : [];
  const contract = meta.contract || null;
  const controls = meta.controls || null;
  const pvpEnabled = Boolean(game && game.pvp_enabled);

  // 对手策略来自 game.yaml 的 opponents / ai_strategies —— match_engine._checked_controller
  // 也是把两处合并后校验，这里保持一致，避免前端给出服务端不认的 strategy。
  const strategies = useMemo(() => {
    const raw = [...(meta.opponents || []), ...(meta.ai_strategies || [])];
    return [...new Set(raw.map(String).filter(Boolean))];
  }, [meta]);

  const models = useMemo(() => {
    const rows = (modelsQuery.data && modelsQuery.data.models) || [];
    // GET /api/v1/models 只返回自己的模型；再显式过滤游戏 / active / 归属，
    // 防止旧数据或别的游戏模型混进 controller。
    return rows.filter(
      (model) =>
        model.game === slug &&
        model.status === "active" &&
        model.owner_id != null &&
        (!user || model.owner_id === user.id),
    );
  }, [modelsQuery.data, slug, user]);

  // 座位数必须和服务端 seat_count() 一致：game.yaml 的 seats 优先，否则只有
  // 声明了 PvP / 内置对手的游戏才是 2 座；ai_strategies 不代表第二个座位
  // （snake / tetris 是单座游戏，策略用于服务端托管演示）。
  const seatCount = useMemo(() => {
    const declared = Number(meta.seats) || 0;
    if (declared) return declared;
    const hasPvp = pvpEnabled || Boolean(meta.pvp && meta.pvp.enabled)
      || (Array.isArray(meta.opponents) && meta.opponents.length > 0);
    return hasPvp ? 2 : 1;
  }, [meta.seats, meta.pvp, meta.opponents, pvpEnabled]);

  // 单座：自己玩 / AI 演示（服务端托管我的座位）/ 我的模型代打；
  // 双座：人类 vs AI / 人类 vs 我的模型（对面）/ 模型代打我的座位（对手用 AI）。
  const options = [];
  if (seatCount >= 2) {
    if (strategies.length > 0) options.push({ key: "ai", label: "人类 vs AI" });
    if (models.length > 0) options.push({ key: "model", label: "人类 vs 我的模型" });
    if (models.length > 0 && strategies.length > 0) {
      options.push({ key: "model-self", label: "模型代打我" });
    }
  } else {
    options.push({ key: "solo", label: "自己玩" });
    if (strategies.length > 0) options.push({ key: "ai", label: "AI 演示" });
    if (models.length > 0) options.push({ key: "model", label: "模型代打" });
  }
  const activeChoice = options.some((item) => item.key === choice)
    ? choice
    : options[0]
      ? options[0].key
      : null;
  const activeStrategy = strategies.includes(strategy) ? strategy : strategies[0] || null;
  const activeModel =
    models.find((model) => String(model.id) === String(modelId)) || models[0] || null;

  const create = async () => {
    if (!loggedIn) {
      openAuth("login");
      return;
    }
    let seedNumber;
    const seedText = seed.trim();
    if (seedText) {
      if (!/^\d+$/.test(seedText) || !Number.isSafeInteger(Number(seedText))) {
        toast.warning("seed 需为非负整数（留空表示随机）");
        return;
      }
      seedNumber = Number(seedText);
    }
    if (options.length === 0) {
      toast.info("该游戏没有可配置的单机对手，请去对战大厅约战");
      return;
    }
    const needsModel = activeChoice === "model" || activeChoice === "model-self";
    const needsStrategy = activeChoice === "ai" || activeChoice === "model-self";
    if (needsModel && !activeModel) {
      toast.warning("先选择一个模型");
      return;
    }
    if (needsStrategy && !activeStrategy) {
      toast.warning("先选择一个 AI 策略");
      return;
    }
    const human = { type: "human" };
    const aiSeat = { type: "ai", strategy: activeStrategy };
    // 只有需要模型时才读 activeModel.id（"ai" 分支下 activeModel 可能是 null）。
    const modelSeat = needsModel
      ? { type: "model", model_id: Number(activeModel.id) }
      : null;
    let seats;
    if (seatCount >= 2) {
      if (activeChoice === "ai") {
        seats = [
          { seat: "p0", occupant: "me", controller: human },
          { seat: "p1", occupant: null, controller: aiSeat },
        ];
      } else if (activeChoice === "model") {
        seats = [
          { seat: "p0", occupant: "me", controller: human },
          { seat: "p1", occupant: null, controller: modelSeat },
        ];
      } else {
        seats = [
          { seat: "p0", occupant: "me", controller: modelSeat },
          { seat: "p1", occupant: null, controller: aiSeat },
        ];
      }
    } else if (activeChoice === "ai") {
      seats = [{ seat: "p0", occupant: "me", controller: aiSeat }];
    } else if (activeChoice === "model") {
      seats = [{ seat: "p0", occupant: "me", controller: modelSeat }];
    } else {
      seats = [{ seat: "p0", occupant: "me", controller: human }];
    }
    // 单机练习：kind=pve 时 mode 只能是 practice；unlisted 不进大厅列表。
    const body = { game: slug, seats, mode: "practice", visibility: "unlisted" };
    if (seedNumber !== undefined) body.settings = { seed: seedNumber };
    setCreating(true);
    try {
      const view = await post("/api/v2/matches", body, token);
      if (!mountedRef.current) return;
      if (!view || !view.id) {
        toast.error("服务端没有返回对局 id");
        return;
      }
      toast.success(
        activeChoice === "model" && seatCount >= 2
          ? "对局已创建，模型坐在对面自动出招"
          : activeChoice === "model" || activeChoice === "model-self"
            ? "对局已创建，模型代打你的座位"
            : activeChoice === "ai" && seatCount < 2
              ? "对局已创建，AI 演示会自动推进"
              : "对局已创建",
      );
      navigate(`/m/${view.id}`);
    } catch (e) {
      if (!mountedRef.current) return;
      if (e && (e.code === "login_required" || e.status === 401)) {
        toast.error("登录已过期，请重新登录");
        openAuth("login");
      } else {
        toast.error(errorText(e));
      }
    } finally {
      if (mountedRef.current) setCreating(false);
    }
  };

  if (gamesQuery.loading && !gamesQuery.data) return <Loading label="加载游戏环境" />;

  if (gamesQuery.error) {
    return (
      <>
        <div className="lab-page-head">
          <div className="lab-page-head__copy">
            <h1 className="lab-h1">单机准备</h1>
            <p className="lab-subtitle">{String(slug || "").toUpperCase()} · 练习局</p>
          </div>
        </div>
        <ErrorNote error={gamesQuery.error} onRetry={gamesQuery.reload} />
      </>
    );
  }

  if (!game) {
    return (
      <div className="lab-card">
        <EmptyState
          icon={<Gamepad2 size={16} />}
          title="无法加载游戏"
          desc="游戏不存在或未公开。"
          action={
            <LinkButton variant="outline" size="sm" href="/environments">
              <ArrowLeft size={13} />
              回到环境列表
            </LinkButton>
          }
        />
      </div>
    );
  }

  const gameTitle = meta.title || game.name || slug;
  const hints = controlHints(controls);
  const leaderboard = (leaderboardQuery.data && leaderboardQuery.data.items) || [];
  const outShape = contract && Array.isArray(contract.out_shape) ? contract.out_shape : null;
  const hudText = hud.length
    ? hud.map((item) => item.label || item.kind || "—").join(" / ")
    : "—";
  // 模型列表是异步的：还没有 AI 策略时，登录用户的模型可能稍后到达，
  // 先按"可配置"渲染，避免闪一下"更适合人类对战"的空态。
  const awaitingModels = seatCount === 2 && strategies.length === 0 && modelsQuery.loading;
  const canConfigure = seatCount === 1 || options.length > 0 || awaitingModels;

  return (
    <>
      <div className="lab-page-head">
        <div className="lab-page-head__copy">
          <div className="lab-row" style={{ gap: 10, flexWrap: "wrap" }}>
            <h1 className="lab-h1">{gameTitle}</h1>
            <Chip>{String(slug).toUpperCase()}</Chip>
            {meta.version ? <Chip>v{meta.version}</Chip> : null}
            <Pill tone="neutral" dot>
              单机准备
            </Pill>
          </div>
          <p className="lab-subtitle">
            {meta.description || game.description || "选择对手后开始一局练习；对局在 /m/:id 舞台进行。"}
          </p>
        </div>
        <div className="lab-page-head__actions">
          <LinkButton variant="outline" size="sm" href={`/environments/${slug}`}>
            <Gamepad2 size={13} />
            环境详情
          </LinkButton>
          {pvpEnabled ? (
            <LinkButton variant="primary" size="sm" href={pvpPath}>
              <Swords size={13} />
              人类对战大厅
            </LinkButton>
          ) : null}
        </div>
      </div>

      <div className="play-layout">
        <div className="play-main">
          {canConfigure ? (
            <div className="play-board-panel">
              <div className="play-board-head">
                <span className="envp-preview__live">
                  <i aria-hidden="true" /> MATCH SETUP
                </span>
                <div className="lab-row" style={{ gap: 8 }}>
                  <Pill tone="neutral">PRACTICE</Pill>
                  <span className="play-board-note">
                    {seatCount} SEAT{seatCount > 1 ? "S" : ""} · PRACTICE · UNLISTED
                  </span>
                </div>
              </div>

              <div style={{ display: "flex", gap: 18, flexWrap: "wrap", alignItems: "flex-start" }}>
                <div
                  style={{
                    flex: "1 1 200px",
                    maxWidth: 260,
                    display: "flex",
                    flexDirection: "column",
                    gap: 10,
                  }}
                >
                  <div className="play-mini">
                    <MiniBoard game={slug} size="lg" tag={null} />
                  </div>
                  <span className="play-board-note">
                    {board ? `BOARD ${board.width}×${board.height}` : "RENDER PREVIEW"}
                  </span>
                </div>

                <div
                  style={{
                    flex: "1 1 300px",
                    minWidth: 0,
                    display: "flex",
                    flexDirection: "column",
                    gap: 12,
                  }}
                >
                  {awaitingModels ? (
                    <Loading label="载入可代打的模型" />
                  ) : options.length > 1 ? (
                    <Tabs
                      items={options.map((item) => ({ key: item.key, label: item.label }))}
                      value={activeChoice || ""}
                      onChange={setChoice}
                    />
                  ) : (
                    <p className="lab-subtitle" style={{ margin: 0, fontSize: 11.5 }}>
                      {seatCount >= 2
                        ? "当前没有可配置的单机对手，去大厅约战或上传模型。"
                        : "单座练习：自己玩；也可以让服务端 AI 或你的模型代打。"}
                    </p>
                  )}
                  {activeChoice === "ai" ? (
                    <Field
                      label="AI 策略"
                      hint={seatCount >= 2
                        ? "对手座位由服务端托管，练习局不计 ELO"
                        : "服务端托管你的座位自动演示，练习局不计 ELO"}
                    >
                      <select
                        className="lab-select"
                        value={activeStrategy || ""}
                        onChange={(event) => setStrategy(event.target.value)}
                      >
                        {strategies.map((item) => (
                          <option key={item} value={item}>
                            {item}
                          </option>
                        ))}
                      </select>
                    </Field>
                  ) : null}
                  {activeChoice === "model" || activeChoice === "model-self" ? (
                    <Field
                      label="我的模型"
                      hint={activeChoice === "model-self"
                        ? "模型代打 p0；p1 由 AI 策略托管"
                        : "只列出属于你、且通过契约校验的 active 模型"}
                    >
                      {modelsQuery.loading ? (
                        <Loading label="载入模型" />
                      ) : models.length ? (
                        <select
                          className="lab-select"
                          value={activeModel ? String(activeModel.id) : ""}
                          onChange={(event) => setModelId(event.target.value)}
                        >
                          {models.map((model) => (
                            <option key={model.id} value={model.id}>
                              {model.name} · #{model.id}
                            </option>
                          ))}
                        </select>
                      ) : (
                        <span className="lab-subtitle" style={{ fontSize: 11.5 }}>
                          还没有可用于本环境的模型。去{" "}
                          <Link className="lab-link lab-link--lime" to="/models">
                            模型工作台
                          </Link>{" "}
                          上传 ONNX 后即可让模型代打。
                        </span>
                      )}
                    </Field>
                  ) : null}
                  {activeChoice === "model-self" ? (
                    <Field label="对手 AI 策略">
                      <select
                        className="lab-select"
                        value={activeStrategy || ""}
                        onChange={(event) => setStrategy(event.target.value)}
                      >
                        {strategies.map((item) => (
                          <option key={item} value={item}>
                            {item}
                          </option>
                        ))}
                      </select>
                    </Field>
                  ) : null}

                  <Field
                    label="随机种子（可选）"
                    hint="留空 = 随机；指定 seed 的练习局不会进入排行榜"
                  >
                    <input
                      className="lab-input"
                      value={seed}
                      placeholder="例如 42"
                      inputMode="numeric"
                      onChange={(event) => setSeed(event.target.value)}
                    />
                  </Field>

                  <div className="lab-row" style={{ gap: 8 }}>
                    <Button
                      variant="primary"
                      onClick={create}
                      disabled={creating || awaitingModels || options.length === 0}
                    >
                      <PlayIcon size={13} />
                      {creating ? "创建中…" : "开始对局"}
                    </Button>
                    {pvpEnabled ? (
                      <LinkButton variant="outline" size="sm" href={pvpPath}>
                        <Swords size={13} />
                        去大厅约战
                      </LinkButton>
                    ) : null}
                  </div>
                  {!loggedIn ? (
                    <span className="lab-subtitle" style={{ fontSize: 10.5 }}>
                      游客可以查看环境信息；开始对局需要登录。
                    </span>
                  ) : null}
                </div>
              </div>
            </div>
          ) : (
            <div className="lab-card">
              <EmptyState
                icon={<Swords size={16} />}
                title={pvpEnabled ? "这个环境更适合人类对战" : "暂时没有可用的单机对手"}
                desc={
                  !loggedIn && contract
                    ? "登录后可以用自己已托管的模型代打；也可以去人类对战大厅约战。"
                    : "没有可配置的 AI 策略或模型对手，请到人类对战大厅创建/加入房间。"
                }
                action={
                  pvpEnabled ? (
                    <LinkButton variant="primary" size="sm" href={pvpPath}>
                      <Swords size={13} />
                      进入对战大厅
                    </LinkButton>
                  ) : !loggedIn ? (
                    <Button variant="primary" size="sm" onClick={() => openAuth("login")}>
                      登录 / 注册
                    </Button>
                  ) : null
                }
              />
            </div>
          )}

          <div className="lab-card" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <div className="lab-card__head">
              <span className="lab-card__title">HUMAN VS HUMAN</span>
              <Swords size={12} style={{ color: "var(--lab-text-3)" }} />
            </div>
            {pvpEnabled ? (
              <>
                <p className="lab-subtitle" style={{ margin: 0, fontSize: 11.5, lineHeight: 1.65 }}>
                  两个人类座位就是 PvP：在大厅创建公开/私有房间、输入邀请码，或快速匹配。
                  创建的房间会直接进入 <span className="lab-mono">/m/:id</span> 舞台。
                </p>
                <div className="lab-row" style={{ gap: 8 }}>
                  <LinkButton variant="outline" size="sm" href={pvpPath}>
                    <Users size={13} />
                    进入对战大厅
                  </LinkButton>
                  <LinkButton variant="outline" size="sm" href="/models">
                    <Box size={13} />
                    托管模型
                  </LinkButton>
                </div>
              </>
            ) : (
              <p className="lab-subtitle" style={{ margin: 0, fontSize: 11.5 }}>
                该环境没有声明 PvP 能力（game.yaml 未开启 pvp.enabled），只能单机练习。
              </p>
            )}
          </div>
        </div>

        <aside className="play-side">
          <div className="lab-card" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <div className="lab-card__head">
              <span className="lab-card__title">GAME INFO</span>
              <span className="lab-mono" style={{ fontSize: 8 }}>
                {meta.version ? `v${meta.version}` : "—"}
              </span>
            </div>
            <div className="play-kv">
              <span>棋盘</span>
              <b>{board ? `${board.width}×${board.height}` : "—"}</b>
            </div>
            <div className="play-kv">
              <span>HUD</span>
              <b style={{ textAlign: "right", maxWidth: 170 }}>{hudText}</b>
            </div>
            <div className="play-kv">
              <span>动作空间</span>
              <b>{outShape ? `[${outShape.join(", ")}]` : "—"}</b>
            </div>
            <div className="play-kv">
              <span>座位</span>
              <b>{seatCount}</b>
            </div>
            <div className="play-kv">
              <span>AI 策略</span>
              <b style={{ textAlign: "right", maxWidth: 170 }}>
                {strategies.length ? strategies.join(", ") : "—"}
              </b>
            </div>
            {hints.length ? (
              <>
                <hr className="lab-rule" />
                <div className="play-keys">
                  {hints.map((hint) => (
                    <span className="play-key" key={hint.key}>
                      <b>{hint.key}</b>
                      {hint.label}
                    </span>
                  ))}
                </div>
              </>
            ) : null}
          </div>

          <div className="lab-card" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <div className="lab-card__head">
              <span className="lab-card__title">LEADERBOARD</span>
              <span className="lab-mono" style={{ fontSize: 8 }}>ELO TOP 10</span>
            </div>
            {leaderboardQuery.error ? (
              <ErrorNote error={leaderboardQuery.error} onRetry={leaderboardQuery.reload} />
            ) : leaderboard.length === 0 ? (
              <EmptyState
                icon={<Trophy size={15} />}
                title="暂无记录"
                desc="完成一局不计 seed 的对局后，服务端会自动把成绩入榜。"
              />
            ) : (
              leaderboard.slice(0, 10).map((item, index) => (
                <div className="play-lb-row" key={item.user_id != null ? item.user_id : index}>
                  <span className={`play-lb-rank${index === 0 ? " is-top" : ""}`}>
                    #{index + 1}
                  </span>
                  <span className="play-lb-name">
                    {item.name}
                    {user && item.user_id === user.id ? "（我）" : ""}
                  </span>
                  <span className="play-lb-score">{item.rating != null ? item.rating : "—"}</span>
                </div>
              ))
            )}
          </div>

          <div className="lab-card" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <span className="lab-card__title">FAIR PLAY</span>
            <span className="lab-subtitle" style={{ fontSize: 11, lineHeight: 1.65 }}>
              分数由服务端在结算时读取对局状态自动入榜，客户端不能自报；指定 seed 的练习局
              可以离线搜索最优解，因此不会进入排行榜。
            </span>
            <span className="lab-mono" style={{ fontSize: 8 }}>
              POST /api/v2/matches → /m/:id
            </span>
          </div>

          {!loggedIn ? (
            <div className="lab-card" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              <div className="lab-card__head">
                <span className="lab-card__title">LOGIN</span>
                <Bot size={12} style={{ color: "var(--lab-text-3)" }} />
              </div>
              <span className="lab-subtitle" style={{ fontSize: 11 }}>
                登录后可以开始练习局、托管模型并参与 PvP。
              </span>
              <Button variant="primary" size="sm" onClick={() => openAuth("login")}>
                登录 / 注册
              </Button>
            </div>
          ) : null}
        </aside>
      </div>
    </>
  );
}
