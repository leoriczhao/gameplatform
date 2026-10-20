import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import {
  Copy, Flag, Send, Users, Gamepad2, ArrowLeftIcon, Swords, PlusIcon,
  ZapIcon, TicketIcon, HomeIcon, SearchIcon, TrophyIcon,
} from "lucide-react";
import { useLogin } from "../components/LoginProvider.jsx";
import { useAuth } from "../AuthContext.jsx";
import { post, getJson, del } from "../api.js";
import { createOpenEnvClient } from "../openenv.js";
import { Button } from "../components/ui/button.jsx";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "../components/ui/card.jsx";
import { Badge } from "../components/ui/badge.jsx";
import { Input } from "../components/ui/input.jsx";
import { RadioGroup, RadioGroupItem } from "../components/ui/radio-group.jsx";
import { Stat } from "../components/ui/stat.jsx";
import { PageHeader } from "../components/ui/page-header.jsx";
import { Alert, AlertDescription, AlertTitle } from "../components/ui/alert.jsx";
import { Confirm } from "../components/ui/confirm.jsx";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../components/ui/dialog.jsx";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "../components/ui/tabs.jsx";
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "../components/ui/table.jsx";
import { EmptyState } from "../components/ui/empty-state.jsx";
import { Spinner } from "../components/ui/spinner.jsx";
import UgBoard from "../components/UgBoard.jsx";

const POLL_MS = 2000;
const SIDE_NAME = { p0: "先手", p1: "后手" };
const UNIT_TYPES = ["worker", "light", "heavy", "ranged", "barracks", "base"];

/* 通用联网 PvP（14 重构）：三 Tab —— 找对手（公开房间+搜索+快速匹配+邀请码）/
   对局（棋盘/指令构建器/聊天/认输/重赛）/ 排行榜（ELO 总榜+周榜）。
   原「对战中心」的找对手与排行榜下沉到每个 PvP 游戏的对战页。 */
export default function UgPvp() {
  const { slug } = useParams();
  const [searchParams] = useSearchParams();
  const { user, token, authReady } = useAuth();
  const openLogin = useLogin();

  const sessRef = useRef(null);
  const stateRef = useRef(null);
  const chatSinceRef = useRef(0);
  const chatListRef = useRef(null);
  const roomPollRef = useRef(null);
  const quickPollRef = useRef(null);
  const [, setUiTick] = useState(0);
  const bump = useCallback(() => setUiTick((t) => t + 1), []);

  const [meta, setMeta] = useState(null);
  const [info, setInfo] = useState(null);
  const [tab, setTab] = useState("find");
  const [rooms, setRooms] = useState([]);
  const [roomSearch, setRoomSearch] = useState("");
  const [quickMode, setQuickMode] = useState("ranked");
  const [queue, setQueue] = useState(null);
  const [ratings, setRatings] = useState([]);
  const [weeklyBoard, setWeeklyBoard] = useState([]);
  const [boardScope, setBoardScope] = useState("total");
  const [hasSess, setHasSess] = useState(false);
  const [joinCode, setJoinCode] = useState("");
  const [over, setOver] = useState(null);
  const [copyOk, setCopyOk] = useState(false);
  const [createMode, setCreateMode] = useState("casual");
  const [createVisibility, setCreateVisibility] = useState("private");
  const [chosen, setChosen] = useState(null);
  const [submitted, setSubmitted] = useState(false);
  const [chat, setChat] = useState([]);
  const [chatText, setChatText] = useState("");
  // unit 型指令构建器状态
  const [selUnit, setSelUnit] = useState(null);
  const [cmdIdx, setCmdIdx] = useState(null);
  const [dirIdx, setDirIdx] = useState(0);
  const [unitType, setUnitType] = useState("worker");
  const [pending, setPending] = useState([]);

  const actionType = (meta?.pvp?.action) || "choice";
  const choices = (meta?.pvp?.choices?.length && meta.pvp.choices)
    || (info?.choices?.length && info.choices) || [];
  const actions = info?.actions || {};          // {cmd: "label"}
  const dirs = info?.directions || {0: "N", 1: "E", 2: "S", 3: "W"};
  const mySide = sessRef.current ? sessRef.current.side : "p0";
  const myOwner = mySide === "p0" ? 0 : 1;
  const myRating = ratings.find((r) => r.user_id === user?.id);

  useEffect(() => {
    const controller = new AbortController();
    const env = createOpenEnvClient(slug, { signal: controller.signal });
    setMeta(null); setInfo(null);
    (async () => {
      try {
        const cat = await getJson("/api/games", null, controller.signal);
        if (controller.signal.aborted) return;
        const g = (cat.games || []).find((x) => x.id === slug);
        const catalogMeta = g?.meta || {};
        const snap = await env.state();
        if (controller.signal.aborted) return;
        const inf = snap?.environment;
        setMeta((inf && inf.meta) || catalogMeta);
        setInfo(inf || {
          game: slug,
          version: catalogMeta.version,
          actions: catalogMeta.actions,
          directions: catalogMeta.directions,
          choices: catalogMeta.pvp?.choices || catalogMeta.choices,
          meta: catalogMeta,
        });
      } catch (e) {
        if (!controller.signal.aborted) toast.error("无法加载游戏：" + e.message);
      } finally {
        env.close();
      }
    })();
    return () => { controller.abort(); env.close(); };
  }, [slug]);

  /* 离开页面时退出房间/对局（等待中/进行中才释放；已结束的 pvp_resign 是 no-op） */
  useEffect(() => {
    return () => {
      const sess = sessRef.current;
      if (sess) {
        post("/api/v1/" + slug + "/play/sessions/" + sess.id + "/leave", {}, token)
          .catch(() => {});
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slug, token]);

  useEffect(() => () => {
    clearInterval(roomPollRef.current);
  }, []);

  const enter = useCallback((data) => {
    const sess = { ...data.session, side: data.side };
    sessRef.current = sess;
    stateRef.current = sess.state;
    setChosen(null);
    setSubmitted(false);
    setSelUnit(null);
    setPending([]);
    setOver(null);
    setHasSess(true);
    setChat([]);
    chatSinceRef.current = 0;
    setTab("play");
    bump();
  }, [bump]);

  const createRoom = useCallback(async (modeOv, visOv) => {
    try {
      const data = await post("/api/v1/" + slug + "/play/sessions",
        { kind: "pvp", mode: modeOv ?? createMode, visibility: visOv ?? createVisibility }, token);
      enter(data);
      toast.success("房间已创建，邀请码 " + data.invite);
    } catch (e) { toast.error("创建失败：" + e.message); }
  }, [slug, token, enter, createMode, createVisibility]);

  const joinRoom = useCallback(async () => {
    const code = joinCode.trim().toUpperCase();
    if (code.length < 6) { toast.warning("请输入 6 位邀请码"); return; }
    try {
      const data = await post("/api/v1/" + slug + "/play/sessions",
        { kind: "pvp", invite: code }, token);
      enter(data);
      toast.success("已加入对局！");
    } catch (e) { toast.error("加入失败：" + e.message); }
  }, [slug, joinCode, token, enter]);

  const joinPublicRoom = useCallback(async (roomId) => {
    try {
      await post("/api/v1/" + slug + "/play/rooms/" + roomId + "/join", {}, token);
      const d = await getJson("/api/v1/" + slug + "/play/sessions/" + roomId, token);
      enter(d);
      toast.success("已加入房间，对局开始！");
    } catch (e) {
      toast.error("加入失败：" + e.message);
      loadRoomsPublic();
    }
  }, [slug, token, enter]);

  const loadRoomsPublic = useCallback(async () => {
    try {
      const d = await getJson("/api/v1/" + slug + "/play/rooms", token);
      setRooms(d.rooms || []);
    } catch (e) { /* keep */ }
  }, [slug, token]);

  useEffect(() => {
    if (!user || !token || tab !== "find") return undefined;
    loadRoomsPublic();
    const t = setInterval(loadRoomsPublic, 5000);
    roomPollRef.current = t;
    return () => clearInterval(t);
  }, [user, token, tab, loadRoomsPublic]);

  const loadRatings = useCallback(async () => {
    try {
      const d = await getJson("/api/v1/ratings/" + slug, token);
      setRatings(d.items || []);
    } catch (e) { /* keep */ }
  }, [slug, token]);

  const loadWeeklyBoard = useCallback(async () => {
    try {
      const d = await getJson("/api/v1/leaderboards/" + slug + "?scope=weekly", token);
      setWeeklyBoard(d.items || []);
    } catch (e) { /* keep */ }
  }, [slug, token]);

  useEffect(() => {
    if (!user || !token || tab !== "rank") return;
    loadRatings();
    if (boardScope === "weekly") loadWeeklyBoard();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user, token, tab, boardScope, loadRatings, loadWeeklyBoard]);

  const stopQuickPoll = () => {
    clearInterval(quickPollRef.current);
    quickPollRef.current = null;
  };

  const startQueue = async () => {
    try {
      const data = await post("/api/v1/" + slug + "/matchmaking/queue",
        { mode: quickMode }, token);
      if (data.matched) {
        const d = await getJson("/api/v1/" + slug + "/play/sessions/" + data.session_id, token);
        enter(d);
        toast.success("已匹配到对手，进入对局！");
        return;
      }
      setQueue(data);
      toast.info("已进入匹配队列（第 " + data.position + " 位）…");
      quickPollRef.current = setInterval(async () => {
        try {
          const d = await getJson("/api/v1/" + slug + "/matchmaking/status", token);
          if (d.matched && d.session_id) {
            stopQuickPoll();
            setQueue(null);
            const sd = await getJson("/api/v1/" + slug + "/play/sessions/" + d.session_id, token);
            enter(sd);
            toast.success("已匹配到对手，进入对局！");
          } else if (!d.queued) {
            stopQuickPoll();
            setQueue(null);
            toast.warning("已不在匹配队列中（可能超时或已被取消）");
          } else {
            setQueue(d);
          }
        } catch (e) { /* transient */ }
      }, 2000);
    } catch (e) {
      toast.error("进入队列失败：" + e.message);
    }
  };

  const cancelQueue = async () => {
    try {
      await del("/api/v1/" + slug + "/matchmaking/queue", token);
    } catch (e) { /* already gone */ }
    stopQuickPoll();
    setQueue(null);
    toast.info("已取消匹配");
  };

  const rematch = useCallback(async () => {
    const sess = sessRef.current;
    if (!sess) return;
    try {
      const data = await post("/api/v1/" + slug + "/play/sessions/" + sess.id + "/rematch",
        {}, token);
      enter(data);
      toast.success("已开新对局！先后手互换");
    } catch (e) { toast.error("再来一局失败：" + e.message); }
  }, [slug, token, enter]);

  const leave = useCallback(async () => {
    const sess = sessRef.current;
    if (sess) {
      try { await post("/api/v1/" + slug + "/play/sessions/" + sess.id + "/leave", {}, token); }
      catch (e) { /* gone */ }
    }
    sessRef.current = null;
    stateRef.current = null;
    setHasSess(false);
    setOver(null);
    setJoinCode("");
    setTab("find");
    bump();
  }, [slug, token, bump]);

  const resign = useCallback(async () => {
    const sess = sessRef.current;
    if (!sess) return;
    try {
      const d = await post("/api/v1/" + slug + "/play/sessions/" + sess.id + "/leave",
        {}, token);
      setOver({ winner: d.winner, cause: "resigned" });
      bump();
    } catch (e) { toast.error("操作失败：" + e.message); }
  }, [slug, token, bump]);

  /* ------------------------------------------------- unit 型指令构建器 */
  const addCmd = () => {
    if (selUnit === null) { toast.warning("先在棋盘上点选己方单位"); return; }
    if (cmdIdx === null) { toast.warning("选择一条指令"); return; }
    const entry = [selUnit, cmdIdx, dirIdx];
    if (cmdIdx === 4 || cmdIdx === 5) entry.push(unitType);
    setPending((xs) => [...xs, entry]);
    setSelUnit(null);
    setCmdIdx(null);
    bump();
  };

  const onCellClick = (x, y) => {
    if (submitted) { toast.info("本回合已提交，等待对手…"); return; }
    const s = stateRef.current;
    const u = (s?.units || []).find((k) => k.x === x && k.y === y);
    if (u && u.owner === myOwner) {
      setSelUnit(u.id);
      setCmdIdx(null);
      bump();
    } else if (u) {
      toast.info("这是对手单位");
    }
  };

  const submit = useCallback(async () => {
    const sess = sessRef.current;
    if (!sess || sess.status !== "active" || submitted) return;
    let action;
    if (actionType === "choice") {
      if (chosen === null) { toast.warning("先选择一个动作"); return; }
      action = chosen;
    } else {
      if (pending.length === 0) { toast.warning("先构建指令（可提交空回合）"); }
      action = pending;
    }
    try {
      const d = await post("/api/v1/" + slug + "/play/sessions/" + sess.id + "/actions",
        { actions: action }, token);
      stateRef.current = d.state;
      if (d.advanced) {
        setSubmitted(false);
        setChosen(null);
        setPending([]);
        toast.success("双方已提交，回合推进！");
      } else {
        setSubmitted(true);
        toast.info("已提交，等待对手…");
      }
      if (d.done) setOver({ winner: d.winner, cause: d.cause });
      bump();
    } catch (e) { toast.error("提交失败：" + e.message); }
  }, [slug, token, submitted, chosen, pending, actionType, bump]);

  const poll = useCallback(async () => {
    const sess = sessRef.current;
    if (!sess || (sess.status !== "waiting" && sess.status !== "active")) return;
    try {
      const d = await getJson("/api/v1/" + slug + "/play/sessions/" + sess.id, token);
      const next = { ...d.session, side: d.side ?? sess.side };
      const tickBefore = sess.state?.tick;
      sessRef.current = next;
      stateRef.current = next.state;
      if (submitted && next.state?.tick !== tickBefore) {
        setSubmitted(false);
        setChosen(null);
      }
      if (next.status === "finished" && sess.status !== "finished") {
        setOver({ winner: next.winner, cause: next.cause });
      }
      try {
        const c = await getJson(
          "/api/v1/" + slug + "/play/sessions/" + sess.id + "/chat?since=" + chatSinceRef.current,
          token);
        if (c.messages && c.messages.length) {
          chatSinceRef.current = c.next_since;
          setChat((prev) => [...prev, ...c.messages]);
        }
      } catch (e2) { /* chat optional */ }
      bump();
    } catch (e) {
      if (e.status === 404) {
        sessRef.current = null;
        stateRef.current = null;
        setHasSess(false);
        setOver(null);
        bump();
      }
    }
  }, [slug, token, submitted, bump]);

  useEffect(() => {
    if (!hasSess) return undefined;
    const t = setInterval(poll, POLL_MS);
    return () => clearInterval(t);
  }, [hasSess, poll]);

  /* 断线重连 / 跳转：?session= 恢复对局；?create=1 自动建房；?join=1 聚焦加入 */
  const sessionParam = searchParams.get("session");
  useEffect(() => {
    if (sessionParam) setTab("play");
    if (!user || !token || !sessionParam || hasSess) return undefined;
    getJson("/api/v1/" + slug + "/play/sessions/" + sessionParam, token)
      .then((d) => {
        if (!d.side) { toast.warning("你不是该对局的玩家（仅观战）"); return; }
        enter(d);
      })
      .catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionParam, user, token, slug, hasSess]);

  useEffect(() => {
    if (searchParams.get("create") === "1" && user && !hasSess) {
      setTab("find");
      const t = setTimeout(createRoom, 400);
      return () => clearTimeout(t);
    }
    if (searchParams.get("join") === "1" && user) {
      setTab("find");
      const el = document.querySelector("input[placeholder='邀请码']");
      if (el) el.focus();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams, user, hasSess]);

  const sendChat = useCallback(async () => {
    const text = chatText.trim();
    const sess = sessRef.current;
    if (!text || !sess) return;
    try {
      await post("/api/v1/" + slug + "/play/sessions/" + sess.id + "/chat",
        { text }, token);
      setChatText("");
      const c = await getJson(
        "/api/v1/" + slug + "/play/sessions/" + sess.id + "/chat?since=" + chatSinceRef.current,
        token);
      if (c.messages && c.messages.length) {
        chatSinceRef.current = c.next_since;
        setChat((prev) => [...prev, ...c.messages]);
      }
    } catch (e) { toast.error("发送失败：" + e.message); }
  }, [slug, chatText, token]);

  const copyInvite = async () => {
    try {
      await navigator.clipboard.writeText(sessRef.current.invite);
      setCopyOk(true);
      toast.success("邀请码已复制");
    } catch (e) { toast.warning("手动复制：" + sessRef.current.invite); }
  };

  const sess = sessRef.current;
  const s = stateRef.current;
  const waiting = sess && sess.status === "waiting";
  const playing = sess && sess.status === "active";
  const sel = selUnit != null && s ? (s.units || []).find((u) => u.id === selUnit) : null;
  const filteredRooms = rooms.filter((r) => {
    const q = roomSearch.trim().toLowerCase();
    if (!q) return true;
    return (r.host || "").toLowerCase().includes(q) || (r.invite || "").toLowerCase().includes(q);
  });

  const chatPanel = (
    <Card className="w-[300px]">
      <CardHeader><CardTitle className="text-sm">房间聊天</CardTitle></CardHeader>
      <CardContent className="flex flex-col gap-2">
        <div ref={chatListRef} className="h-[160px] overflow-y-auto rounded-lg border border-border bg-background/60 p-2">
          {chat.length === 0 && <p className="text-xs text-muted-foreground">还没有消息</p>}
          {chat.map((m) => (
            <div key={m.id} className="mb-2">
              <p className="text-[11px] text-muted-foreground">{m.nickname}</p>
              <div className={
                "mt-0.5 rounded-lg border px-2 py-1 text-[13px] " +
                (m.user_id === user?.id ? "border-indigo-500/40 bg-indigo-500/10" : "border-border bg-neutral-100")
              }>{m.text}</div>
            </div>
          ))}
        </div>
        <div className="flex gap-2">
          <Input placeholder="说点什么…" value={chatText} maxLength={500}
            onChange={(e) => setChatText(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") sendChat(); }} />
          <Button size="icon" onClick={sendChat}><Send className="size-4" /></Button>
        </div>
      </CardContent>
    </Card>
  );

  const findPanel = (
    <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
      <Card>
        <CardHeader className="flex-row items-center gap-2">
          <HomeIcon className="size-4 text-indigo-600" />
          <CardTitle className="text-base">公开房间</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative flex-1">
              <SearchIcon className="absolute left-2.5 top-2.5 size-4 text-muted-foreground" />
              <Input className="pl-8" placeholder="搜索房主 / 邀请码" value={roomSearch}
                onChange={(e) => setRoomSearch(e.target.value)} />
            </div>
            <Button onClick={() => createRoom("casual", "public")}>
              <Users className="size-4" /> 创建公开房间
            </Button>
          </div>
          <div className="mt-3">
            {filteredRooms.length === 0 ? (
              <EmptyState icon={HomeIcon} title={rooms.length ? "没有匹配的房间" : "暂无等待中的公开房间"}
                description="点上方按钮创建一个吧" />
            ) : (
              <Table>
                <TableHeader><TableRow>
                  <TableHead>房主</TableHead><TableHead className="w-20">模式</TableHead>
                  <TableHead className="w-24">邀请码</TableHead><TableHead className="w-24">创建时间</TableHead>
                  <TableHead className="w-28">操作</TableHead>
                </TableRow></TableHeader>
                <TableBody>
                  {filteredRooms.map((r) => (
                    <TableRow key={r.id}>
                      <TableCell>{r.host_id === user?.id ? <b>{r.host}（我）</b> : r.host}</TableCell>
                      <TableCell>{r.mode === "ranked" ? <Badge variant="warning">排位</Badge> : <Badge variant="success">练习</Badge>}</TableCell>
                      <TableCell className="font-mono text-sm text-indigo-700">{r.invite}</TableCell>
                      <TableCell>{new Date(r.created_at * 1000).toLocaleTimeString("zh-CN", { hour12: false })}</TableCell>
                      <TableCell>
                        {r.host_id === user?.id ? <Badge variant="secondary">我的房间</Badge>
                          : <Button size="sm" onClick={() => joinPublicRoom(r.id)}>加入</Button>}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </div>
          <p className="mt-3 text-xs text-muted-foreground">
            公开房间任何人可见可加入；排位局结算 ELO，练习局不计分。列表每 5 秒刷新。
          </p>
        </CardContent>
      </Card>

      <div className="flex flex-col gap-5">
        <Card>
          <CardHeader className="flex-row items-center gap-2">
            <ZapIcon className="size-4 text-indigo-600" />
            <CardTitle className="text-base">快速匹配</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex flex-col items-center gap-3 py-2 text-center">
              <p className="text-sm text-muted-foreground">
                一键排队，系统按 ELO 撮合旗鼓相当的对手；等得越久，积分范围放宽越大。
              </p>
              <RadioGroup value={quickMode} disabled={!!queue} onValueChange={setQuickMode} className="flex gap-3">
                <label className="flex items-center gap-1.5 text-sm"><RadioGroupItem value="ranked" /> 排位 ranked（计 ELO）</label>
                <label className="flex items-center gap-1.5 text-sm"><RadioGroupItem value="casual" /> 练习 casual（不计分）</label>
              </RadioGroup>
              {queue ? (
                <>
                  <div className="flex items-center gap-2 text-sm"><Spinner size="sm" className="py-0" />
                    <span>排队中… 位置 #{queue.position} · 已等待 {queue.wait_seconds} 秒</span></div>
                  <Button variant="destructive" size="sm" onClick={cancelQueue}>取消匹配</Button>
                </>
              ) : (<Button onClick={startQueue}><ZapIcon /> 开始匹配</Button>)}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex-row items-center gap-2">
            <TicketIcon className="size-4 text-indigo-600" />
            <CardTitle className="text-base">邀请码开房 / 加入</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div className="flex flex-col gap-2">
                <span className="text-xs text-muted-foreground">创建私有房间，拿邀请码发给朋友</span>
                <div className="flex flex-col gap-2">
                  <RadioGroup value={createMode} onValueChange={setCreateMode} className="flex gap-3">
                    <label className="flex items-center gap-1.5 text-sm"><RadioGroupItem value="casual" /> 练习</label>
                    <label className="flex items-center gap-1.5 text-sm"><RadioGroupItem value="ranked" /> 排位</label>
                  </RadioGroup>
                  <Button variant="outline" size="sm" onClick={() => createRoom(null, "private")}>
                    <Users className="size-4" /> 创建私有房间
                  </Button>
                </div>
              </div>
              <div className="flex flex-col gap-2">
                <span className="text-xs text-muted-foreground">输入朋友的 6 位邀请码</span>
                <div className="flex gap-2">
                  <Input placeholder="邀请码" value={joinCode} maxLength={6} className="uppercase"
                    onChange={(e) => setJoinCode(e.target.value.toUpperCase())}
                    onKeyDown={(e) => { if (e.key === "Enter") joinRoom(); }} />
                  <Button onClick={joinRoom}>加入</Button>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );

  const rankPanel = (
    <Card>
      <CardHeader className="flex-row items-center gap-2">
        <TrophyIcon className="size-4 text-indigo-600" />
        <CardTitle className="text-base">{(meta?.title || slug)} 排行榜</CardTitle>
        {myRating && <Badge variant="warning"><TrophyIcon className="size-3" /> 我的 ELO：{myRating.rating}（{myRating.games} 局）</Badge>}
      </CardHeader>
      <CardContent>
        <Tabs value={boardScope} onValueChange={(k) => { setBoardScope(k); if (k === "weekly") loadWeeklyBoard(); }}>
          <TabsList><TabsTrigger value="total">总榜（ELO）</TabsTrigger><TabsTrigger value="weekly">周榜（近 7 天）</TabsTrigger></TabsList>
          <TabsContent value="total">
            {ratings.length === 0 ? (<EmptyState icon={TrophyIcon} title="还没有人打过 PvP" description="来开第一局吧" />) : (
              <Table>
                <TableHeader><TableRow>
                  <TableHead className="w-20">排名</TableHead><TableHead>玩家</TableHead>
                  <TableHead className="text-right">ELO</TableHead><TableHead className="w-20 text-right">局数</TableHead><TableHead className="w-16 text-right">胜</TableHead>
                </TableRow></TableHeader>
                <TableBody>
                  {ratings.map((r, i) => (
                    <TableRow key={r.user_id}>
                      <TableCell>{i === 0 ? <TrophyIcon className="size-4 text-amber-400" /> : `#${i + 1}`}</TableCell>
                      <TableCell>{r.user_id === user?.id ? <b>{r.name}（我）</b> : r.name}</TableCell>
                      <TableCell className="text-right"><b className="tabular-nums">{r.rating}</b></TableCell>
                      <TableCell className="text-right tabular-nums">{r.games}</TableCell>
                      <TableCell className="text-right tabular-nums">{r.wins}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
            <p className="mt-4 text-xs text-muted-foreground">每局 ranked 按 ELO 结算（K=32，起始 1200）；平局各得半分。casual 与模型对战不计分。</p>
          </TabsContent>
          <TabsContent value="weekly">
            {weeklyBoard.length === 0 ? (<EmptyState icon={TrophyIcon} title="本周还没有人打 PvP" />) : (
              <Table>
                <TableHeader><TableRow>
                  <TableHead className="w-20">排名</TableHead><TableHead>玩家</TableHead>
                  <TableHead className="w-20 text-right">胜场</TableHead><TableHead className="w-20 text-right">局数</TableHead><TableHead className="w-24 text-right">本周 XP</TableHead>
                </TableRow></TableHeader>
                <TableBody>
                  {weeklyBoard.map((r, i) => (
                    <TableRow key={r.user_id}>
                      <TableCell>{i === 0 ? <TrophyIcon className="size-4 text-amber-400" /> : `#${i + 1}`}</TableCell>
                      <TableCell>{r.user_id === user?.id ? <b>{r.name}（我）</b> : r.name}</TableCell>
                      <TableCell className="text-right"><b className="tabular-nums">{r.wins}</b></TableCell>
                      <TableCell className="text-right tabular-nums">{r.games}</TableCell>
                      <TableCell className="text-right tabular-nums">{r.xp}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
            <p className="mt-4 text-xs text-muted-foreground">按最近 7 天胜场数排名（同胜场看局数，再看本周 XP）。</p>
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  );

  return (
    <div className="page-shell">
      <PageHeader
        icon={Swords}
        title={(meta?.title || slug) + " · 对战"}
        description={"验证支线 · /games/" + slug + "/pvp · 非对战中心"}
        actions={(
          <>
            {user ? <Badge variant="info">{user.nickname || user.username}</Badge>
              : <Button size="sm" onClick={openLogin}>登录</Button>}
            <Button asChild variant="ghost" size="sm"><Link to={"/games/" + slug}><ArrowLeftIcon /> 单机</Link></Button>
            <Button asChild variant="ghost" size="sm"><Link to="/"><Gamepad2 /> 大厅</Link></Button>
          </>
        )}
      />

      {!user && authReady && (
        <Alert variant="info" className="mb-5">
          <AlertTitle>PvP 需要登录</AlertTitle>
          <AlertDescription>联网对战与 ELO 积分都需要账号。</AlertDescription>
        </Alert>
      )}

      {user && (
        <Tabs value={tab} onValueChange={setTab} className="mb-3">
          <TabsList>
            <TabsTrigger value="find"><HomeIcon className="size-4" /> 找对手</TabsTrigger>
            <TabsTrigger value="play"><Gamepad2 className="size-4" /> 对局</TabsTrigger>
            <TabsTrigger value="rank"><TrophyIcon className="size-4" /> 排行榜</TabsTrigger>
          </TabsList>
        </Tabs>
      )}

      {user && tab === "find" && (
        <p className="mb-3 text-sm font-medium">在本游戏内验证</p>
      )}

      {user && tab === "find" && (
        <>
          {findPanel}
          <p className="mt-3 text-center text-[11px] text-muted-foreground">
            无 /arena · 无跨游戏选战大厅 · 模型对抗在{" "}
            <Link to="/models" className="text-indigo-600 hover:underline">/models</Link>
          </p>
        </>
      )}

      {user && tab === "play" && (
        <>
          {!sess && (
            <div className="flex justify-center py-10">
              <EmptyState icon={Gamepad2} title="还没有对局"
                description="切到「找对手」加入公开房间 / 快速匹配 / 输入邀请码" />
            </div>
          )}
          {waiting && (
            <div className="flex flex-wrap justify-center gap-5">
              <Card className="w-[420px]">
                <CardHeader><CardTitle className="text-sm">等待对手加入…</CardTitle></CardHeader>
                <CardContent className="flex flex-col items-center gap-4">
                  <div className="text-4xl font-bold tracking-[6px] gradient-text tabular-nums">{sess.invite}</div>
                  <div className="flex flex-wrap gap-1.5">
                    <Badge variant={sess.mode === "ranked" ? "warning" : "success"}>
                      {sess.mode === "ranked" ? "排位 ranked（计 ELO）" : "练习 casual（不计分）"}
                    </Badge>
                    <Badge variant={sess.visibility === "public" ? "info" : "outline"}>
                      {sess.visibility === "public" ? "公开房间" : "私有房间"}
                    </Badge>
                  </div>
                  <Button variant="outline" onClick={copyInvite}><Copy className="size-4" /> {copyOk ? "已复制 ✓" : "复制邀请码"}</Button>
                  <Confirm title="确定取消房间？" confirmText="取消房间" cancelText="继续等待" onConfirm={leave}>
                    <Button variant="destructive">取消房间</Button>
                  </Confirm>
                </CardContent>
              </Card>
              {chatPanel}
            </div>
          )}
          {playing && (
            <div className="flex flex-wrap justify-center gap-5">
              <div className="flex flex-col items-center gap-4">
                <UgBoard state={s} meta={meta} onCellClick={actionType === "unit" ? onCellClick : null} />
                <div className="flex flex-wrap justify-center gap-2">
                  {actionType === "choice" ? (
                    choices.map((c, i) => (
                      <Button key={i} variant={chosen === i ? "default" : "outline"} disabled={submitted} onClick={() => setChosen(i)}>
                        {c}
                      </Button>
                    ))
                  ) : (
                    <div className="flex flex-col items-center gap-2">
                      <div className="flex flex-wrap justify-center gap-1.5">
                        {Object.entries(actions).map(([k, label]) => (
                          <Button key={k} size="sm" variant={cmdIdx === Number(k) ? "default" : "outline"} disabled={submitted} onClick={() => setCmdIdx(Number(k))}>
                            {k} {String(label).split("(")[0]}
                          </Button>
                        ))}
                      </div>
                      <div className="flex flex-wrap justify-center items-center gap-1.5">
                        <span className="text-xs text-muted-foreground">方向</span>
                        {Object.entries(dirs).map(([k, label]) => (
                          <Button key={k} size="sm" variant={dirIdx === Number(k) ? "default" : "outline"} disabled={submitted} onClick={() => setDirIdx(Number(k))}>
                            {label}
                          </Button>
                        ))}
                        {(cmdIdx === 4 || cmdIdx === 5) && (
                          <>
                            <span className="text-xs text-muted-foreground">类型</span>
                            <select className="rounded-md border border-border bg-background px-1.5 py-1 text-sm" value={unitType} disabled={submitted}
                              onChange={(e) => setUnitType(e.target.value)}>
                              {UNIT_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
                            </select>
                          </>
                        )}
                        <Button size="sm" variant="secondary" disabled={submitted} onClick={addCmd}><PlusIcon className="size-4" /> 添加指令</Button>
                      </div>
                      {pending.length > 0 && (
                        <div className="flex flex-wrap justify-center gap-1.5">
                          {pending.map((entry, i) => (
                            <Badge key={i} variant="secondary" className="cursor-pointer" title="点击移除"
                              onClick={() => setPending((xs) => xs.filter((_, j) => j !== i))}>
                              #{entry[0]} {String(actions[entry[1]] || entry[1]).split("(")[0]}
                              {dirs[entry[2]] ? " " + dirs[entry[2]] : ""}
                              {entry[3] ? " " + entry[3] : ""} ✕
                            </Badge>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                  <Button disabled={submitted} onClick={submit}>
                    <Send className="size-4" /> {submitted ? "已提交，等待对手…" : "提交本回合"}
                  </Button>
                  <Confirm title="确定认输？" confirmText="认输" cancelText="继续" onConfirm={resign}>
                    <Button variant="destructive"><Flag className="size-4" /> 认输</Button>
                  </Confirm>
                </div>
              </div>

              <div className="flex w-[300px] flex-col gap-4">
                <Card>
                  <CardHeader><CardTitle className="text-sm">对局信息</CardTitle></CardHeader>
                  <CardContent className="flex flex-col gap-3">
                    <div className="flex flex-wrap gap-1.5">
                      {(sess.players || []).map((p) => (
                        <Badge key={p.side} variant={p.side === "p0" ? "info" : "destructive"}>
                          {SIDE_NAME[p.side]} {p.name || "…"}{p.submitted ? " · 已提交 ✓" : ""}
                        </Badge>
                      ))}
                    </div>
                    <p className="text-xs text-muted-foreground">我的阵营：<b className="text-foreground">{SIDE_NAME[mySide]}</b></p>
                    <Stat label="TICK" value={s ? s.tick : 0} />
                    {actionType === "unit" && sel && (
                      <p className="text-xs text-muted-foreground">已选单位 #{sel.id}（{sel.type}）@ ({sel.x},{sel.y})</p>
                    )}
                  </CardContent>
                </Card>
                {chatPanel}
              </div>
            </div>
          )}
        </>
      )}

      {user && tab === "rank" && rankPanel}

      <Dialog open={!!over} onOpenChange={() => {}}>
        <DialogContent showCloseButton={false} className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="gradient-text">
              {over && (over.winner === (mySide === "p0" ? 0 : 1) ? "你赢了！"
                : over.winner === null ? "平局" : "你输了")}
            </DialogTitle>
            <DialogDescription>
              {over && (over.cause === "timeout" && "一方连续超时被判负")}
              {over && (over.cause === "resigned" && "一方认输，对局结束")}
              {over && (!over.cause && "对局结束")}
            </DialogDescription>
          </DialogHeader>
          {over && (
            <div className="flex flex-wrap gap-2">
              <Button onClick={rematch}>再来一局（互换先后手）</Button>
              <Button variant="outline" onClick={leave}>返回找对手</Button>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}