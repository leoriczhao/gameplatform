import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { toast } from "sonner";
import { BotIcon, Gamepad2Icon, TrophyIcon, ArrowLeftIcon, UploadIcon, SwordsIcon } from "lucide-react";
import { post, getJson } from "../api.js";
import { createOpenEnvClient } from "../openenv.js";
import { useAuth } from "../AuthContext.jsx";
import { useLogin } from "../components/LoginProvider.jsx";
import { Button } from "../components/ui/button.jsx";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card.jsx";
import { Badge } from "../components/ui/badge.jsx";
import { Input } from "../components/ui/input.jsx";
import { PageHeader } from "../components/ui/page-header.jsx";
import { Stat } from "../components/ui/stat.jsx";
import { EmptyState } from "../components/ui/empty-state.jsx";
import { Spinner } from "../components/ui/spinner.jsx";
import { Alert } from "../components/ui/alert.jsx";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../components/ui/dialog.jsx";
import UgBoard from "../components/UgBoard.jsx";
import { relativeAction } from "../games.js";

/* BoardFrame：视口 max-height + 内部 transform 缩放，解耦棋盘格数对整页高度的影响。
   CHANGE-20261016-ugplay-layout / ui-handoff + mock. */
function BoardFrame({ children, fitKey }) {
  const frameRef = useRef(null);
  const hostRef = useRef(null);
  const innerRef = useRef(null);
  const [box, setBox] = useState({ scale: 1, w: 0, h: 0 });

  useLayoutEffect(() => {
    const frame = frameRef.current;
    const host = hostRef.current;
    const inner = innerRef.current;
    if (!frame || !host || !inner) return undefined;

    const fit = () => {
      // 先解除宿主约束，量自然尺寸，再算 scale
      host.style.width = "auto";
      host.style.height = "auto";
      host.style.overflow = "visible";
      inner.style.transform = "none";
      const bw = inner.offsetWidth;
      const bh = inner.offsetHeight;
      const style = getComputedStyle(frame);
      const padX = (parseFloat(style.paddingLeft) || 0) + (parseFloat(style.paddingRight) || 0);
      const padY = (parseFloat(style.paddingTop) || 0) + (parseFloat(style.paddingBottom) || 0);
      const fw = frame.clientWidth - padX;
      const maxH = Math.min(window.innerHeight * 0.7, 640) - padY;
      if (bw < 1 || bh < 1 || fw < 1 || maxH < 1) return;
      const s = Math.min(1, fw / bw, maxH / bh);
      const w = Math.ceil(bw * s);
      const h = Math.ceil(bh * s);
      host.style.width = w + "px";
      host.style.height = h + "px";
      host.style.overflow = "hidden";
      inner.style.transform = `scale(${s})`;
      setBox((prev) => (prev.scale === s && prev.w === w && prev.h === h
        ? prev
        : { scale: s, w, h }));
    };

    fit();
    // 等 UgBoard 异步画完后再量一次
    const t = requestAnimationFrame(fit);
    const ro = new ResizeObserver(() => fit());
    ro.observe(frame);
    window.addEventListener("resize", fit);
    return () => {
      cancelAnimationFrame(t);
      ro.disconnect();
      window.removeEventListener("resize", fit);
    };
  }, [fitKey]);

  return (
    <div ref={frameRef} className="ug-board-frame">
      <div ref={hostRef} className="ug-board-scaler-host">
        <div
          ref={innerRef}
          className="ug-board-scaler"
          style={{ transform: `scale(${box.scale})`, transformOrigin: "top left" }}
        >
          {children}
        </div>
      </div>
    </div>
  );
}

/* UGC 单机页 /games/:slug（11 P4）：通用棋盘渲染 + 人工 PvE +
   内置 AI 演示（ai_strategies）+ 提交分数 + 排行榜。 */
export default function UgPlay() {
  const { slug } = useParams();
  const { user, token, authReady } = useAuth();
  const openLogin = useLogin();

  const [meta, setMeta] = useState(null);
  const [info, setInfo] = useState(null);
  const [pvpEnabled, setPvpEnabled] = useState(false);
  const [state, setState] = useState(null);
  const [preview, setPreview] = useState(null);   // 未登录时的只读初始棋盘
  const [sessionId, setSessionId] = useState(null);
  const [over, setOver] = useState(null);
  const [matchId, setMatchId] = useState(null);
  const [aiMode, setAiMode] = useState(false);
  const [leaderboard, setLeaderboard] = useState([]);
  const [actionInput, setActionInput] = useState("");
  const [rankMsg, setRankMsg] = useState(null);
  const [loadErr, setLoadErr] = useState(null);
  const [submitName, setSubmitName] = useState(
    localStorage.getItem("ugc-name") || "");

  const sessRef = useRef(null);
  const stateRef = useRef(null);
  const pendingRef = useRef(false);

  const choices = (info?.choices?.length && info.choices)
    || (meta?.pvp?.choices?.length && meta.pvp.choices) || null;
  const hasAI = !!(meta?.ai_strategies?.length);
  const hasModelChallenge = !!meta?.contract;

  /* ------------------------------------------------------------- bootstrap */

  useEffect(() => {
    const controller = new AbortController();
    const env = createOpenEnvClient(slug, { signal: controller.signal });
    setMeta(null); setInfo(null); setPreview(null); setLoadErr(null);
    (async () => {
      try {
        const cat = await getJson("/api/games", null, controller.signal);
        if (controller.signal.aborted) return;
        const g = (cat.games || []).find((x) => x.id === slug);
        if (!g) throw new Error("游戏不存在或未公开");
        const snap = await env.state();
        if (controller.signal.aborted) return;
        // OpenEnv state 契约含 environment；线上曾只回 {episode_id,step_count}。
        // 缺 environment 时用目录 meta 兜底，禁止读 inf.meta 抛未捕获。
        const catalogMeta = g.meta || {};
        const inf = snap?.environment;
        setMeta((inf && inf.meta) || catalogMeta);
        setPvpEnabled(!!g.pvp_enabled);
        setInfo(inf || {
          game: slug,
          version: catalogMeta.version,
          action_space: g.action_space || catalogMeta.action_space,
          choices: g.choices || catalogMeta.choices || catalogMeta.pvp?.choices,
          meta: catalogMeta,
        });
      } catch (e) {
        if (!controller.signal.aborted) setLoadErr(e.message);
      } finally {
        env.close();
      }
    })();
    getJson("/api/" + slug + "/scores?limit=10", null, controller.signal)
      .then((d) => { if (!controller.signal.aborted) setLeaderboard(d.items || []); })
      .catch(() => {});
    return () => { controller.abort(); env.close(); };
  }, [slug]);

  const newGame = useCallback(async () => {
    if (!user) { openLogin(); return; }        // 未登录：引导登录，不发无效请求
    const old = sessRef.current;
    if (old) {
      try {
        await post("/api/v1/" + slug + "/play/sessions/" + old + "/leave", {}, token);
      } catch { /* 旧局可能已结束/失效，忽略 */ }
    }
    try {
      const d = await post("/api/v1/" + slug + "/play/sessions", {}, token);
      sessRef.current = d.session.id;
      stateRef.current = d.session.state;
      setSessionId(d.session.id);
      setState(d.session.state);
      setOver(null);
      setMatchId(null);
      setRankMsg(null);
      setActionInput("");
    } catch (e) {
      // 开局失败必须可见：以前是 unhandled rejection → 页面空白无提示
      if (e && e.status === 401) {
        toast.error("登录已过期，请重新登录");
        openLogin();
      } else {
        toast.error("无法开始对局：" + e.message);
      }
    }
  }, [slug, token, user, openLogin]);

  useEffect(() => {
    if (!authReady) return;
    // 游玩需要登录（游客只能看棋盘与排行榜）
    if (meta && info?.game === slug && user) newGame();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authReady, meta, info, user, slug]);

  /* 游客预览：短暂 OpenEnv WS 环境取完整初始局面，随后销毁；不建平台对局。 */
  useEffect(() => {
    if (!authReady || user || info?.game !== slug) return undefined;
    const controller = new AbortController();
    const env = createOpenEnvClient(slug, { signal: controller.signal });
    env.reset({ seed: 42, version: info.version, obs_mode: "state" })
      .then((d) => { if (!controller.signal.aborted) setPreview(d.observation.state || null); })
      .catch(() => { /* 预览失败就保持动作空间文字 */ })
      .finally(() => env.close());
    return () => { controller.abort(); env.close(); };
  }, [authReady, user, info, slug]);

  /* 离开页面时释放游玩会话（否则游客 1 局/30 分钟会挡新开局） */
  useEffect(() => {
    return () => {
      const sid = sessRef.current;
      if (sid) {
        post("/api/v1/" + slug + "/play/sessions/" + sid + "/leave", {}, token)
          .catch(() => {});
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slug, token]);

  /* ------------------------------------------------------------ step loop */

  const doStep = useCallback(async (action) => {
    if (pendingRef.current || !sessRef.current) return;
    pendingRef.current = true;
    try {
      const expected = stateRef.current?.tick ?? 0;
      const d = await post(
        "/api/v1/" + slug + "/play/sessions/" + sessRef.current + "/actions",
        { actions: action, expected_tick: expected }, token);
      stateRef.current = d.state;
      setState(d.state);
      if (d.done) {
        setAiMode(false);
        setMatchId(d.match_id ?? null);
        setOver({ cause: d.cause, winner: d.winner, state: d.state });
      }
    } catch (e) {
      toast.error(e.message);
      setAiMode(false);
      if (e.status === 409) {
        // 状态过期（重试/并发）：刷新快照后由玩家重新决策
        try {
          const d = await getJson(
            "/api/v1/" + slug + "/play/sessions/" + sessRef.current, token);
          stateRef.current = d.session.state;
          setState(d.session.state);
        } catch { /* keep old snapshot */ }
      }
    } finally {
      pendingRef.current = false;
    }
  }, [slug, token]);

  /* ------------------------------------------------------ controls 键盘（13 G4） */

  const controls = meta?.controls;

  useEffect(() => {
    if (!controls || !user) return undefined;
    const onKey = (ev) => {
      if (stateRef.current?.done || aiMode || pendingRef.current) return;
      const bind = controls.keys?.[ev.code];
      if (!bind) return;
      ev.preventDefault();
      const [val] = bind;
      if (controls.mode === "relative-turn") {
        const cur = stateRef.current?.[controls.direction_field];
        const rel = cur == null ? null : relativeAction(cur, val);
        if (rel !== null) doStep(rel);
      } else {
        doStep(val);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [controls, aiMode, doStep, user]);

  const submitChoice = (idx) => {
    if (state?.done) return;
    doStep(idx);
  };

  const submitNumber = () => {
    if (state?.done) return;
    const n = Number(actionInput);
    if (!Number.isInteger(n)) { toast.warning("请输入一个整数动作"); return; }
    doStep(n);
  };

  /* ------------------------------------------------------------- AI autopilot */

  const aiTick = useCallback(async () => {
    if (pendingRef.current || stateRef.current?.done) return;
    pendingRef.current = true;
    try {
      const s = stateRef.current;
      const strat = (meta?.ai_strategies || ["default"])[0];
      const d = await post("/api/" + slug + "/ai/action",
        { state: s, strategy: strat }, token);
      pendingRef.current = false;
      const action = d && d.action !== undefined ? d.action : d;
      await doStep(action);
    } catch (e) {
      pendingRef.current = false;
      toast.error("AI 请求失败：" + e.message);
      setAiMode(false);
    }
  }, [slug, token, meta, doStep]);

  useEffect(() => {
    if (!aiMode || state?.done) return;
    const t = setInterval(aiTick, 350);
    return () => clearInterval(t);
  }, [aiMode, state?.done, aiTick]);

  const loadLeaderboard = useCallback(async () => {
    try {
      const d = await getJson("/api/" + slug + "/scores?limit=10");
      setLeaderboard(d.items || []);
    } catch (e) { /* keep */ }
  }, [slug]);

  const submitScore = async (name) => {
    if (!matchId) {
      toast.error("该对局没有服务端记录，无法上榜");
      return;
    }
    try {
      // 分数由服务端从这场对局读取，客户端不再自报
      const d = await post("/api/" + slug + "/scores",
        { match_id: matchId, name }, token);
      localStorage.setItem("ugc-name", name);
      setRankMsg("已上榜！当前排名 #" + d.rank);
      loadLeaderboard();
    } catch (e) {
      toast.error("提交失败：" + e.message);
    }
  };

  if (loadErr) {
    return (
      <div className="page-shell">
        <Alert variant="destructive">
          <div className="font-semibold">无法加载游戏</div>
          <div className="text-sm opacity-90">{loadErr}</div>
          <div className="mt-3">
            <Button asChild size="sm" variant="outline"><Link to="/"><ArrowLeftIcon /> 回大厅</Link></Button>
          </div>
        </Alert>
      </div>
    );
  }

  if (!meta || !info) {
    return <div className="page-shell"><Spinner size="lg" text="加载游戏…" /></div>;
  }

  const score = Math.round(Number(state?.score ?? state?.reward ?? 0));

  return (
    <div className="page-shell">
      <PageHeader
        icon={Gamepad2Icon}
        title={(meta.title || slug) + " · UGC"}
        description={meta.description || info.action_space || ""}
        actions={(
          <>
            <Stat label="得分" value={score} valueClassName="text-emerald-600" />
            {pvpEnabled && (
              <Button asChild variant="secondary" size="sm">
                <Link to={`/games/${slug}/pvp`}><SwordsIcon /> 去对战</Link>
              </Button>
            )}
            <Badge variant="secondary">UGC</Badge>
            {meta.author ? <Badge variant="outline">作者 {meta.author}</Badge> : null}
            <Button asChild variant="ghost" size="sm"><Link to="/"><ArrowLeftIcon /> 大厅</Link></Button>
          </>
        )}
      />

      <div className="ug-play-grid">
        <div className="ug-board-col">
          {(() => {
            const shown = state || preview;
            if (shown?.board || shown?.render_board) {
              const fitKey = [
                slug,
                shown?.tick ?? "",
                Array.isArray(shown?.board) ? shown.board.length : "",
                Array.isArray(shown?.render_board) ? shown.render_board.length : "",
              ].join(":");
              return (
                <>
                  <BoardFrame fitKey={fitKey}>
                    <UgBoard state={shown} meta={meta} />
                  </BoardFrame>
                  {!state && preview && (
                    <Badge variant="secondary">棋盘预览（登录后可操作）</Badge>
                  )}
                </>
              );
            }
            return info.action_space
              ? <p className="text-sm text-muted-foreground">动作空间：{info.action_space}</p>
              : null;
          })()}

          {!user ? (
            <Alert variant="info" className="ug-login-gate">
              <div className="text-sm">
                {preview
                  ? "上面是初始棋盘预览；登录后才能对局并上榜。"
                  : "登录后才能开始对局；游客可以看棋盘和排行榜。"}
              </div>
              <Button size="sm" onClick={openLogin} className="mt-2">登录 / 注册</Button>
            </Alert>
          ) : (
            <>
              <div className="flex flex-wrap justify-center gap-2">
                {choices ? (
                  choices.map((c, i) => (
                    <Button
                      key={i}
                      variant={state?.done ? "outline" : "default"}
                      disabled={state?.done || aiMode}
                      onClick={() => submitChoice(i)}
                    >
                      {c}
                    </Button>
                  ))
                ) : (
                  <div className="flex items-center gap-2">
                    <Input
                      className="w-40"
                      placeholder="动作（整数）"
                      value={actionInput}
                      disabled={state?.done || aiMode}
                      onChange={(e) => setActionInput(e.target.value)}
                      onKeyDown={(e) => { if (e.key === "Enter") submitNumber(); }}
                    />
                    <Button disabled={state?.done || aiMode} onClick={submitNumber}>提交</Button>
                  </div>
                )}
                <Button onClick={() => { if (state?.done) newGame(); else newGame(); }}>
                  再来一局
                </Button>
                {hasAI && (
                  <Button
                    variant={aiMode ? "default" : "secondary"}
                    onClick={() => setAiMode((v) => !v)}
                  >
                    <BotIcon /> {aiMode ? "停止演示" : "内置 AI 演示"}
                  </Button>
                )}
              </div>
              <p className="text-center text-xs text-muted-foreground">
                {choices ? "点击选项推进一回合（服务端权威状态）" : "输入动作整数后提交，每次推进一回合"}
              </p>
            </>
          )}
        </div>

        <aside className="ug-side-col">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="flex items-center gap-2 text-base">
                <TrophyIcon className="size-4 text-indigo-600" /> 排行榜
              </CardTitle>
            </CardHeader>
            <CardContent className="pt-2">
              {leaderboard.length ? (
                <ul className="m-0 flex flex-col gap-0.5 p-0">
                  {leaderboard.map((it) => (
                    <li key={it.rank} className="flex items-center gap-2 py-1.5">
                      <Badge variant={it.rank === 1 ? "warning" : "secondary"}>#{it.rank}</Badge>
                      <span className="min-w-0 flex-1 truncate">{it.name}</span>
                      <b className="tabular-nums">{it.score}</b>
                    </li>
                  ))}
                </ul>
              ) : (
                <EmptyState icon={TrophyIcon} title="暂无记录" className="py-6" />
              )}
            </CardContent>
          </Card>
          {hasModelChallenge && (
            <Button asChild variant="outline" size="sm">
              <Link to="/models"><BotIcon /> 去模型托管发起挑战</Link>
            </Button>
          )}
          <Button asChild variant="ghost" size="sm">
            <Link to="/ugc"><UploadIcon /> 上传我的游戏</Link>
          </Button>
        </aside>
      </div>

      <Dialog open={!!over} onOpenChange={(v) => { if (!v) setOver(null); }}>
        <DialogContent showCloseButton={false} className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle className="gradient-text">
              {over && (over.winner === 0 ? "通关！" : "游戏结束")}
            </DialogTitle>
            {over && <DialogDescription>{over.cause || "—"}</DialogDescription>}
          </DialogHeader>
          {over && (
            <div className="flex flex-col gap-4">
              <Stat label="得分" value={Math.round(Number(over.state?.score ?? over.state?.reward ?? 0))} />
              <div className="flex flex-col gap-3">
                <Input
                  placeholder="你的名字"
                  maxLength={24}
                  value={submitName}
                  onChange={(e) => setSubmitName(e.target.value)}
                />
                <Button className="w-full" onClick={() => {
                  const nm = submitName.trim();
                  if (!nm) { toast.warning("请输入名字"); return; }
                  submitScore(nm);
                }}>提交排行榜</Button>
              </div>
              {rankMsg && <p className="m-0 text-sm text-amber-600">{rankMsg}</p>}
              <Button variant="secondary" className="w-full" onClick={newGame}>再来一局</Button>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
