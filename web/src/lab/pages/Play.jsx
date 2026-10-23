import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import "./play.css";
import { toast } from "sonner";
import {
  ArrowLeft,
  Bot,
  Box,
  Gamepad2,
  Gauge,
  Play as PlayIcon,
  RotateCcw,
  Swords,
  Trophy,
  Upload,
} from "lucide-react";
import BoardFrame from "../BoardFrame.jsx";
import { getJson, post } from "../api.js";
import { createOpenEnvClient } from "../../openenv.js";
import { useAuth } from "../../AuthContext.jsx";
import { useLabAuth } from "../AuthDialog.jsx";
import UgBoard from "../../components/UgBoard.jsx";
import { relativeAction } from "../../games.js";
import {
  Button,
  Chip,
  EmptyState,
  ErrorNote,
  Field,
  LinkButton,
  Loading,
  Modal,
  Pill,
} from "../ui.jsx";

const KEY_GLYPH = {
  ArrowLeft: "←",
  ArrowRight: "→",
  ArrowUp: "↑",
  ArrowDown: "↓",
  Space: "SPACE",
};

function controlHint(controls) {
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
  const { user, token, authReady } = useAuth();
  const { openAuth } = useLabAuth();

  const [meta, setMeta] = useState(null);
  const [info, setInfo] = useState(null);
  const [pvpEnabled, setPvpEnabled] = useState(false);
  const [state, setState] = useState(null);
  const [preview, setPreview] = useState(null);
  const [sessionId, setSessionId] = useState(null);
  const [over, setOver] = useState(null);
  const [matchId, setMatchId] = useState(null);
  const [aiMode, setAiMode] = useState(false);
  const [leaderboard, setLeaderboard] = useState([]);
  const [actionInput, setActionInput] = useState("");
  const [rankMsg, setRankMsg] = useState(null);
  const [loadErr, setLoadErr] = useState(null);
  const [submitName, setSubmitName] = useState(() => {
    try {
      return localStorage.getItem("ugc-name") || "";
    } catch (e) {
      return "";
    }
  });

  const sessRef = useRef(null);
  const stateRef = useRef(null);
  const pendingRef = useRef(false);

  const choices = (info && info.choices && info.choices.length && info.choices)
    || (meta && meta.pvp && meta.pvp.choices && meta.pvp.choices.length && meta.pvp.choices)
    || null;
  const hasAI = Boolean(meta && meta.ai_strategies && meta.ai_strategies.length);
  const hasModelChallenge = Boolean(meta && meta.contract);
  const controls = meta && meta.controls;

  useEffect(() => {
    const controller = new AbortController();
    const env = createOpenEnvClient(slug, { signal: controller.signal });
    setMeta(null);
    setInfo(null);
    setPreview(null);
    setLoadErr(null);
    (async () => {
      try {
        const catalog = await getJson("/api/games", null, controller.signal);
        if (controller.signal.aborted) return;
        const game = (catalog.games || []).find((item) => item.id === slug);
        if (!game) throw new Error("游戏不存在或未公开");
        const snapshot = await env.state();
        if (controller.signal.aborted) return;
        const catalogMeta = game.meta || {};
        const environment = snapshot && snapshot.environment;
        setMeta((environment && environment.meta) || catalogMeta);
        setPvpEnabled(Boolean(game.pvp_enabled));
        setInfo(environment || {
          game: slug,
          version: catalogMeta.version,
          action_space: game.action_space || catalogMeta.action_space,
          choices: game.choices || catalogMeta.choices || (catalogMeta.pvp && catalogMeta.pvp.choices),
          meta: catalogMeta,
        });
      } catch (e) {
        if (!controller.signal.aborted) setLoadErr(e.message || "加载失败");
      } finally {
        env.close();
      }
    })();
    getJson("/api/" + slug + "/scores?limit=10", null, controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) setLeaderboard(data.items || []);
      })
      .catch(() => {});
    return () => {
      controller.abort();
      env.close();
    };
  }, [slug]);

  const loadLeaderboard = useCallback(async () => {
    try {
      const data = await getJson("/api/" + slug + "/scores?limit=10");
      setLeaderboard(data.items || []);
    } catch (e) {
      /* keep */
    }
  }, [slug]);

  const newGame = useCallback(async () => {
    if (!user) {
      openAuth("login");
      return;
    }
    const old = sessRef.current;
    if (old) {
      post("/api/v1/" + slug + "/play/sessions/" + old + "/leave", {}, token).catch(() => {});
    }
    try {
      const data = await post("/api/v1/" + slug + "/play/sessions", {}, token);
      sessRef.current = data.session.id;
      stateRef.current = data.session.state;
      setSessionId(data.session.id);
      setState(data.session.state);
      setOver(null);
      setMatchId(null);
      setRankMsg(null);
      setActionInput("");
    } catch (e) {
      if (e && e.status === 401) {
        toast.error("登录已过期，请重新登录");
        openAuth("login");
      } else {
        toast.error("无法开始对局：" + (e.message || "未知错误"));
      }
    }
  }, [slug, token, user, openAuth]);

  useEffect(() => {
    if (!authReady) return;
    if (!(meta && info && info.game === slug && user)) return undefined;
    let cancelled = false;
    (async () => {
      try {
        const wanted = new URLSearchParams(window.location.search).get("resume");
        const data = await getJson("/api/v1/play/active", token);
        if (cancelled) return;
        const mine = (data.sessions || []).find(
          (item) => item.game === slug && item.kind === "pve" && (!wanted || item.id === wanted),
        ) || (data.sessions || []).find((item) => item.game === slug && item.kind === "pve");
        if (!mine) throw new Error("no active session");
        const detail = await getJson("/api/v1/" + slug + "/play/sessions/" + mine.id, token);
        if (cancelled) return;
        sessRef.current = detail.session.id;
        stateRef.current = detail.session.state;
        setSessionId(detail.session.id);
        setState(detail.session.state);
        setOver(null);
        setMatchId(detail.session.match_id || null);
        toast.info("已恢复未完成的试玩对局");
      } catch (e) {
        if (!cancelled) newGame();
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authReady, meta, info, user, slug, token]);

  useEffect(() => {
    if (!authReady || user || !info || info.game !== slug) return undefined;
    const controller = new AbortController();
    const env = createOpenEnvClient(slug, { signal: controller.signal });
    env.reset({ seed: 42, version: info.version, obs_mode: "state" })
      .then((data) => {
        if (!controller.signal.aborted) setPreview((data.observation && data.observation.state) || null);
      })
      .catch(() => {})
      .finally(() => env.close());
    return () => {
      controller.abort();
      env.close();
    };
  }, [authReady, user, info, slug]);

  useEffect(() => {
    return () => {
      const sid = sessRef.current;
      if (sid) {
        post("/api/v1/" + slug + "/play/sessions/" + sid + "/leave", {}, token).catch(() => {});
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slug, token]);

  const doStep = useCallback(
    async (action) => {
      if (pendingRef.current || !sessRef.current) return;
      pendingRef.current = true;
      try {
        const expected = (stateRef.current && stateRef.current.tick) || 0;
        const data = await post(
          "/api/v1/" + slug + "/play/sessions/" + sessRef.current + "/actions",
          { actions: action, expected_tick: expected },
          token,
        );
        stateRef.current = data.state;
        setState(data.state);
        if (data.done) {
          setAiMode(false);
          setMatchId(data.match_id ?? null);
          setOver({ cause: data.cause, winner: data.winner, state: data.state });
        }
      } catch (e) {
        toast.error(e.message || "操作失败");
        setAiMode(false);
        if (e.status === 409) {
          try {
            const data = await getJson(
              "/api/v1/" + slug + "/play/sessions/" + sessRef.current,
              token,
            );
            stateRef.current = data.session.state;
            setState(data.session.state);
          } catch (err) {
            /* keep old snapshot */
          }
        }
      } finally {
        pendingRef.current = false;
      }
    },
    [slug, token],
  );

  useEffect(() => {
    if (!controls || !user) return undefined;
    const onKey = (event) => {
      if ((stateRef.current && stateRef.current.done) || aiMode || pendingRef.current) return;
      const bind = controls.keys && controls.keys[event.code];
      if (!bind) return;
      event.preventDefault();
      const [value] = bind;
      if (controls.mode === "relative-turn") {
        const current = stateRef.current && stateRef.current[controls.direction_field];
        const rel = current == null ? null : relativeAction(current, value);
        if (rel !== null) doStep(rel);
      } else {
        doStep(value);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [controls, aiMode, doStep, user]);

  const submitChoice = (index) => {
    if (state && state.done) return;
    doStep(index);
  };

  const submitNumber = () => {
    if (state && state.done) return;
    const value = Number(actionInput);
    if (!Number.isInteger(value)) {
      toast.warning("请输入一个整数动作");
      return;
    }
    doStep(value);
  };

  const aiTick = useCallback(async () => {
    if (pendingRef.current || (stateRef.current && stateRef.current.done)) return;
    pendingRef.current = true;
    try {
      const current = stateRef.current;
      const strategy = (meta && meta.ai_strategies && meta.ai_strategies[0]) || "default";
      const data = await post("/api/" + slug + "/ai/action", { state: current, strategy }, token);
      pendingRef.current = false;
      const action = data && data.action !== undefined ? data.action : data;
      await doStep(action);
    } catch (e) {
      pendingRef.current = false;
      toast.error("AI 请求失败：" + (e.message || "未知错误"));
      setAiMode(false);
    }
  }, [slug, token, meta, doStep]);

  useEffect(() => {
    if (!aiMode || (state && state.done)) return undefined;
    const timer = setInterval(aiTick, 350);
    return () => clearInterval(timer);
  }, [aiMode, state && state.done, aiTick]);

  const submitScore = async (name) => {
    if (!matchId) {
      toast.error("该对局没有服务端记录，无法上榜");
      return;
    }
    try {
      const data = await post("/api/" + slug + "/scores", { match_id: matchId, name }, token);
      try {
        localStorage.setItem("ugc-name", name);
      } catch (e) {
        /* ignore */
      }
      setRankMsg("已上榜！当前排名 #" + data.rank);
      loadLeaderboard();
    } catch (e) {
      toast.error("提交失败：" + (e.message || "未知错误"));
    }
  };

  if (loadErr) {
    return (
      <div className="lab-card">
        <EmptyState
          icon={<Gamepad2 size={16} />}
          title="无法加载游戏"
          desc={loadErr}
          action={
            <LinkButton variant="outline" size="sm" href={`/environments/${slug}`}>
              <ArrowLeft size={13} />
              回到环境详情
            </LinkButton>
          }
        />
      </div>
    );
  }

  if (!meta || !info) return <Loading label="加载游戏环境" />;

  const shown = state || preview;
  const score = Math.round(Number((state && (state.score ?? state.reward)) || 0));
  const hints = controlHint(controls);
  const gameTitle = meta.title || slug;
  const fitKey = [
    slug,
    shown && shown.tick,
    Array.isArray(shown && shown.board) ? shown.board.length : "",
    Array.isArray(shown && shown.render_board) ? shown.render_board.length : "",
  ].join(":");

  return (
    <>
      <div className="lab-page-head">
        <div className="lab-page-head__copy">
          <div className="lab-row" style={{ gap: 10, flexWrap: "wrap" }}>
            <h1 className="lab-h1">{gameTitle}</h1>
            <Chip>{String(slug).toUpperCase()}</Chip>
            <Pill tone="neutral" dot>
              验证支线
            </Pill>
            {meta.version ? <Chip>v{meta.version}</Chip> : null}
          </div>
          <p className="lab-subtitle">{meta.description || (info && info.action_space) || "人工试玩与内置 AI 演示"}</p>
        </div>
        <div className="lab-page-head__actions">
          <LinkButton variant="outline" size="sm" href={`/environments/${slug}`}>
            <Gauge size={13} />
            环境详情
          </LinkButton>
          {pvpEnabled ? (
            <LinkButton variant="primary" size="sm" href={`/games/${slug}/pvp`}>
              <Swords size={13} />
              去对战
            </LinkButton>
          ) : null}
          <LinkButton variant="outline" size="sm" href="/models">
            <Box size={13} />
            模型挑战
          </LinkButton>
        </div>
      </div>

      <div className="play-layout">
        <div className="play-main">
          <div className="play-board-panel">
            <div className="play-board-head">
              <span className="envp-preview__live">
                <i aria-hidden="true" /> LIVE BOARD
              </span>
              <div className="lab-row" style={{ gap: 10 }}>
                {state ? (
                  <span className="play-board-note">TICK {state.tick ?? 0}</span>
                ) : (
                  <span className="play-board-note">INITIAL STATE</span>
                )}
                <span className="play-board-note">SERVER-AUTHORITATIVE</span>
              </div>
            </div>
            {shown && (shown.board || shown.render_board) ? (
              <BoardFrame fitKey={fitKey} minHeight={620}>
                <UgBoard state={shown} meta={meta} />
              </BoardFrame>
            ) : (
              <div className="lab-empty">
                <div className="lab-empty__title">当前环境没有可渲染的棋盘</div>
                <p className="lab-empty__desc">
                  {info && info.action_space ? `动作空间：${info.action_space}` : "可以直接提交动作推进对局。"}
                </p>
              </div>
            )}
            <div className="play-status-line">
              <span className="lab-mono" style={{ fontSize: 8 }}>
                {state ? (state.done ? "FINISHED" : "IN PROGRESS") : user ? "READY" : "PREVIEW · 登录后可操作"}
              </span>
              <span className="lab-grow" />
              {state ? <span>奖励 {Math.round(Number(state.reward || 0) * 100) / 100}</span> : null}
            </div>
          </div>

          {!user ? (
            <div className="play-gate">
              <div>
                <div className="lab-empty__title">登录后开始对局</div>
                <p className="lab-empty__desc">
                  {preview
                    ? "上面是初始棋盘预览；登录后可以对局并把分数送上排行榜。"
                    : "游客可以看棋盘与排行榜，对局需要账号。"}
                </p>
              </div>
              <div className="lab-row" style={{ gap: 8 }}>
                <Button variant="primary" onClick={() => openAuth("login")}>
                  登录 / 注册
                </Button>
                <LinkButton variant="outline" href="/environments">
                  看看其它环境
                </LinkButton>
              </div>
            </div>
          ) : (
            <div className="play-controls">
              <div className="play-controls-row">
                {choices ? (
                  choices.map((choice, index) => (
                    <button
                      key={index}
                      type="button"
                      className="play-choice"
                      disabled={Boolean(state && state.done) || aiMode}
                      onClick={() => submitChoice(index)}
                    >
                      {choice}
                    </button>
                  ))
                ) : (
                  <>
                    <input
                      className="play-action-input"
                      placeholder="动作（整数）"
                      value={actionInput}
                      disabled={Boolean(state && state.done) || aiMode}
                      onChange={(event) => setActionInput(event.target.value)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter") submitNumber();
                      }}
                    />
                    <Button
                      variant="primary"
                      disabled={Boolean(state && state.done) || aiMode}
                      onClick={submitNumber}
                    >
                      提交动作
                    </Button>
                  </>
                )}
              </div>
              <div className="play-controls-row">
                <Button variant="outline" size="sm" onClick={newGame}>
                  <RotateCcw size={12} />
                  再来一局
                </Button>
                {hasAI ? (
                  <Button
                    variant={aiMode ? "primary" : "outline"}
                    size="sm"
                    onClick={() => setAiMode((value) => !value)}
                  >
                    <Bot size={12} />
                    {aiMode ? "停止 AI 演示" : "内置 AI 演示"}
                  </Button>
                ) : null}
                {hasModelChallenge ? (
                  <Link className="lab-btn lab-btn--ghost lab-btn--sm" to="/models">
                    <Trophy size={12} />
                    模型托管
                  </Link>
                ) : null}
                <span className="lab-grow" />
                <span className="play-board-note">
                  {choices ? "点击选项推进一回合" : "输入动作整数后提交"}
                </span>
              </div>
              {hints.length ? (
                <div className="play-keys">
                  {hints.map((hint) => (
                    <span className="play-key" key={hint.key}>
                      <b>{hint.key}</b>
                      {hint.label}
                    </span>
                  ))}
                </div>
              ) : null}
            </div>
          )}
        </div>

        <aside className="play-side">
          <div className="lab-card" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <div className="lab-card__head">
              <span className="lab-card__title">CURRENT RUN</span>
              <Pill tone={state ? (state.done ? "neutral" : "green") : "neutral"} dot>
                {state ? (state.done ? "FINISHED" : "LIVE") : "PREVIEW"}
              </Pill>
            </div>
            <div className="play-score">
              <span className="play-score__num">{score}</span>
              <span className="play-score__cap">SCORE</span>
            </div>
            <div className="play-kv">
              <span>游戏</span>
              <b>{String(slug).toUpperCase()}</b>
            </div>
            <div className="play-kv">
              <span>版本</span>
              <b>{meta.version || "—"}</b>
            </div>
            <div className="play-kv">
              <span>动作空间</span>
              <b>{choices ? `choice × ${choices.length}` : (info.action_space || "integer")}</b>
            </div>
            <div className="play-kv">
              <span>会话</span>
              <b>{sessionId ? sessionId.slice(0, 8) : "—"}</b>
            </div>
            <hr className="lab-rule" />
            <span className="lab-mono" style={{ fontSize: 8 }}>
              分数由服务端从对局读取，客户端不能自报。
            </span>
          </div>

          <div className="lab-card" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <div className="lab-card__head">
              <span className="lab-card__title">LEADERBOARD</span>
              <span className="lab-mono" style={{ fontSize: 8 }}>TOP 10</span>
            </div>
            {leaderboard.length === 0 ? (
              <EmptyState icon={<Trophy size={15} />} title="暂无记录" desc="完成一局并提交分数后会出现在这里。" />
            ) : (
              leaderboard.map((item) => (
                <div className="play-lb-row" key={item.rank}>
                  <span className={`play-lb-rank${item.rank === 1 ? " is-top" : ""}`}>
                    #{item.rank}
                  </span>
                  <span className="play-lb-name">{item.name}</span>
                  <span className="play-lb-score">{item.score}</span>
                </div>
              ))
            )}
          </div>

          <div className="lab-card" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <span className="lab-card__title">VALIDATION LAYER</span>
            <span className="lab-subtitle" style={{ fontSize: 11, lineHeight: 1.65 }}>
              网页试玩用同一套游戏引擎核对动力学与规则，不替代训练闭环；对局与分数都会落库。
            </span>
            <Link
              className="lab-btn lab-btn--ghost lab-btn--sm"
              to={`/environments/${slug}`}
              style={{ justifyContent: "flex-start", padding: 0 }}
            >
              <Upload size={12} />
              环境契约与渲染声明
            </Link>
          </div>
        </aside>
      </div>

      {over ? (
        <Modal
          title={over.winner === 0 ? "通关！" : over.winner === null ? "对局结束" : "游戏结束"}
          onClose={() => setOver(null)}
        >
          <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            <div className="play-score">
              <span className="play-score__num">{Math.round(Number((over.state && (over.state.score ?? over.state.reward)) || 0))}</span>
              <span className="play-score__cap">FINAL SCORE</span>
            </div>
            <p className="lab-subtitle" style={{ margin: 0 }}>
              {over.cause || "对局已结束"}
              {matchId ? ` · MATCH #${matchId}` : " · 无服务端记录"}
            </p>
            <Field label="上榜名字" hint="1–24 个字符">
              <input
                className="lab-input"
                value={submitName}
                maxLength={24}
                onChange={(event) => setSubmitName(event.target.value)}
                placeholder="你的名字"
              />
            </Field>
            {rankMsg ? <div className="envp-valid">{rankMsg}</div> : null}
            <div className="lab-modal__actions">
              <Button
                variant="outline"
                onClick={() => {
                  const name = submitName.trim();
                  if (!name) {
                    toast.warning("请输入名字");
                    return;
                  }
                  submitScore(name);
                }}
              >
                提交排行榜
              </Button>
              <Button variant="primary" onClick={newGame}>
                <PlayIcon size={13} />
                再来一局
              </Button>
            </div>
          </div>
        </Modal>
      ) : null}
    </>
  );
}