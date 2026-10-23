import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import "./play.css";
import "./pvp.css";
import { toast } from "sonner";
import {
  ArrowLeft,
  Copy,
  Flag,
  Gamepad2,
  Home,
  Plus,
  Search,
  Send,
  Swords,
  Ticket,
  Trophy,
  Users,
  Zap,
} from "lucide-react";
import { del, getJson, post } from "../api.js";
import { createOpenEnvClient } from "../../openenv.js";
import { useAuth } from "../../AuthContext.jsx";
import { useLabAuth } from "../AuthDialog.jsx";
import BoardFrame from "../BoardFrame.jsx";
import UgBoard from "../../components/UgBoard.jsx";
import {
  Button,
  Chip,
  EmptyState,
  ErrorNote,
  LinkButton,
  Loading,
  Modal,
  Pill,
  Tabs,
} from "../ui.jsx";
import { relativeTime } from "../format.js";

const POLL_MS = 2000;
const SIDE_NAME = { p0: "先手", p1: "后手" };
const UNIT_TYPES = ["worker", "light", "heavy", "ranged", "barracks", "base"];
const DIR_FALLBACK = { 0: "N", 1: "E", 2: "S", 3: "W" };

function ChatPanel({ user, chat, chatText, setChatText, sendChat }) {
  const listRef = useRef(null);
  useEffect(() => {
    if (listRef.current) listRef.current.scrollTop = listRef.current.scrollHeight;
  }, [chat.length]);
  return (
    <div className="lab-card pvp-chat">
      <div className="lab-card__head">
        <span className="lab-card__title">ROOM CHAT</span>
        <span className="lab-mono" style={{ fontSize: 8 }}>轮询 2s</span>
      </div>
      <div className="pvp-chat__list" ref={listRef}>
        {chat.length === 0 ? (
          <span className="pvp-chat__empty">还没有消息，打个招呼吧。</span>
        ) : (
          chat.map((message) => (
            <div
              key={message.id}
              className={`pvp-chat__msg${message.user_id === (user && user.id) ? " is-mine" : ""}`}
            >
              <span className="pvp-chat__who">{message.nickname || "玩家"}</span>
              <span className="pvp-chat__bubble">{message.text}</span>
            </div>
          ))
        )}
      </div>
      <div className="pvp-chat__input">
        <input
          className="lab-input"
          style={{ height: 34 }}
          placeholder="说点什么…"
          value={chatText}
          maxLength={500}
          onChange={(event) => setChatText(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") sendChat();
          }}
        />
        <Button variant="outline" size="sm" onClick={sendChat} title="发送">
          <Send size={13} />
        </Button>
      </div>
    </div>
  );
}

export default function Pvp() {
  const { slug } = useParams();
  const [searchParams] = useSearchParams();
  const { user, token, authReady } = useAuth();
  const { openAuth } = useLabAuth();

  const sessRef = useRef(null);
  const stateRef = useRef(null);
  const chatSinceRef = useRef(0);
  const quickPollRef = useRef(null);
  const joinInputRef = useRef(null);
  const [, setUiTick] = useState(0);
  const bump = useCallback(() => setUiTick((tick) => tick + 1), []);

  const [meta, setMeta] = useState(null);
  const [info, setInfo] = useState(null);
  const [loadErr, setLoadErr] = useState(null);
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
  const [chosen, setChosen] = useState(null);
  const [submitted, setSubmitted] = useState(false);
  const [chat, setChat] = useState([]);
  const [chatText, setChatText] = useState("");
  const [selUnit, setSelUnit] = useState(null);
  const [cmdIdx, setCmdIdx] = useState(null);
  const [dirIdx, setDirIdx] = useState(0);
  const [unitType, setUnitType] = useState("worker");
  const [pending, setPending] = useState([]);

  const actionType = (meta && meta.pvp && meta.pvp.action) || "choice";
  const choices = (meta && meta.pvp && meta.pvp.choices && meta.pvp.choices.length && meta.pvp.choices)
    || (info && info.choices && info.choices.length && info.choices)
    || [];
  const actions = (info && info.actions) || {};
  const dirs = (info && info.directions) || DIR_FALLBACK;
  const sess = sessRef.current;
  const state = stateRef.current;
  const mySide = sess ? sess.side : "p0";
  const myOwner = mySide === "p0" ? 0 : 1;
  const myRating = ratings.find((rating) => rating.user_id === (user && user.id));
  const waiting = sess && sess.status === "waiting";
  const playing = sess && sess.status === "active";
  const selectedUnit = selUnit != null && state ? (state.units || []).find((unit) => unit.id === selUnit) : null;
  const filteredRooms = rooms.filter((room) => {
    const query = roomSearch.trim().toLowerCase();
    if (!query) return true;
    return (room.host || "").toLowerCase().includes(query)
      || (room.invite || "").toLowerCase().includes(query);
  });

  useEffect(() => {
    const controller = new AbortController();
    const env = createOpenEnvClient(slug, { signal: controller.signal });
    setMeta(null);
    setInfo(null);
    setLoadErr(null);
    (async () => {
      try {
        const catalog = await getJson("/api/games", null, controller.signal);
        if (controller.signal.aborted) return;
        const game = (catalog.games || []).find((item) => item.id === slug);
        if (!game) throw new Error("游戏不存在或未公开");
        const catalogMeta = game.meta || {};
        const snapshot = await env.state();
        if (controller.signal.aborted) return;
        const environment = snapshot && snapshot.environment;
        setMeta((environment && environment.meta) || catalogMeta);
        setInfo(environment || {
          game: slug,
          version: catalogMeta.version,
          actions: catalogMeta.actions,
          directions: catalogMeta.directions,
          choices: (catalogMeta.pvp && catalogMeta.pvp.choices) || catalogMeta.choices,
          meta: catalogMeta,
        });
      } catch (e) {
        if (!controller.signal.aborted) setLoadErr(e.message || "无法加载游戏");
      } finally {
        env.close();
      }
    })();
    return () => {
      controller.abort();
      env.close();
    };
  }, [slug]);

  useEffect(() => {
    return () => {
      const current = sessRef.current;
      if (current) {
        post("/api/v1/" + slug + "/play/sessions/" + current.id + "/leave", {}, token).catch(() => {});
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slug, token]);

  const stopQuickPoll = useCallback(() => {
    if (quickPollRef.current) {
      clearInterval(quickPollRef.current);
      quickPollRef.current = null;
    }
  }, []);

  useEffect(() => () => stopQuickPoll(), [stopQuickPoll]);

  const enter = useCallback((data) => {
    const next = { ...data.session, side: data.side };
    sessRef.current = next;
    stateRef.current = next.state;
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

  // U15 断线重连：进入页面时恢复自己进行中的 PvP 对局（banner 链接可带 ?resume=<sid>）
  useEffect(() => {
    if (!user || !token || sessRef.current) return undefined;
    let cancelled = false;
    (async () => {
      try {
        const data = await getJson("/api/v1/play/active", token);
        if (cancelled) return;
        const wanted = searchParams.get("resume");
        const mine = (data.sessions || []).find(
          (item) => item.game === slug && item.kind === "pvp" && (!wanted || item.id === wanted),
        ) || (data.sessions || []).find((item) => item.game === slug && item.kind === "pvp");
        if (!mine) return;
        const detail = await getJson("/api/v1/" + slug + "/play/sessions/" + mine.id, token);
        if (cancelled) return;
        enter({ session: detail.session || mine, side: mine.side || "p0" });
        toast.info("已恢复进行中的对局");
      } catch (e) {
        /* fall back to 找对手 */
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user, token, slug, enter, searchParams]);

  const createRoom = useCallback(async (modeOverride, visibilityOverride) => {
    try {
      const data = await post(
        "/api/v1/" + slug + "/play/sessions",
        { kind: "pvp", mode: modeOverride ?? createMode, visibility: visibilityOverride },
        token,
      );
      enter(data);
      toast.success("房间已创建，邀请码 " + data.invite);
    } catch (e) {
      toast.error("创建失败：" + (e.message || "未知错误"));
    }
  }, [slug, token, enter, createMode]);

  const joinRoom = useCallback(async () => {
    const code = joinCode.trim().toUpperCase();
    if (code.length < 6) {
      toast.warning("请输入 6 位邀请码");
      return;
    }
    try {
      const data = await post("/api/v1/" + slug + "/play/sessions", { kind: "pvp", invite: code }, token);
      enter(data);
      toast.success("已加入对局！");
    } catch (e) {
      toast.error("加入失败：" + (e.message || "未知错误"));
    }
  }, [slug, joinCode, token, enter]);

  const loadRoomsPublic = useCallback(async () => {
    try {
      const data = await getJson("/api/v1/" + slug + "/play/rooms", token);
      setRooms(data.rooms || []);
    } catch (e) {
      /* keep */
    }
  }, [slug, token]);

  const joinPublicRoom = useCallback(async (roomId) => {
    try {
      await post("/api/v1/" + slug + "/play/rooms/" + roomId + "/join", {}, token);
      const data = await getJson("/api/v1/" + slug + "/play/sessions/" + roomId, token);
      enter(data);
      toast.success("已加入房间，对局开始！");
    } catch (e) {
      toast.error("加入失败：" + (e.message || "未知错误"));
      loadRoomsPublic();
    }
  }, [slug, token, enter, loadRoomsPublic]);

  useEffect(() => {
    if (!user || !token || tab !== "find") return undefined;
    loadRoomsPublic();
    const timer = setInterval(loadRoomsPublic, 5000);
    return () => clearInterval(timer);
  }, [user, token, tab, loadRoomsPublic]);

  const loadRatings = useCallback(async () => {
    try {
      const data = await getJson("/api/v1/ratings/" + slug, token);
      setRatings(data.items || []);
    } catch (e) {
      /* keep */
    }
  }, [slug, token]);

  const loadWeeklyBoard = useCallback(async () => {
    try {
      const data = await getJson("/api/v1/leaderboards/" + slug + "?scope=weekly", token);
      setWeeklyBoard(data.items || []);
    } catch (e) {
      /* keep */
    }
  }, [slug, token]);

  useEffect(() => {
    if (!user || !token || tab !== "rank") return undefined;
    loadRatings();
    if (boardScope === "weekly") loadWeeklyBoard();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user, token, tab, boardScope]);

  const startQueue = async () => {
    try {
      const data = await post("/api/v1/" + slug + "/matchmaking/queue", { mode: quickMode }, token);
      if (data.matched) {
        const detail = await getJson("/api/v1/" + slug + "/play/sessions/" + data.session_id, token);
        enter(detail);
        toast.success("已匹配到对手，进入对局！");
        return;
      }
      setQueue(data);
      toast.info("已进入匹配队列（第 " + data.position + " 位）…");
      quickPollRef.current = setInterval(async () => {
        try {
          const status = await getJson("/api/v1/" + slug + "/matchmaking/status", token);
          if (status.matched && status.session_id) {
            stopQuickPoll();
            setQueue(null);
            const detail = await getJson("/api/v1/" + slug + "/play/sessions/" + status.session_id, token);
            enter(detail);
            toast.success("已匹配到对手，进入对局！");
          } else if (!status.queued) {
            stopQuickPoll();
            setQueue(null);
            toast.warning("已不在匹配队列中（可能超时或已被取消）");
          } else {
            setQueue(status);
          }
        } catch (e) {
          /* transient */
        }
      }, 2000);
    } catch (e) {
      toast.error("进入队列失败：" + (e.message || "未知错误"));
    }
  };

  const cancelQueue = async () => {
    try {
      await del("/api/v1/" + slug + "/matchmaking/queue", token);
    } catch (e) {
      /* already gone */
    }
    stopQuickPoll();
    setQueue(null);
    toast.info("已取消匹配");
  };

  const rematch = useCallback(async () => {
    const current = sessRef.current;
    if (!current) return;
    try {
      const data = await post(
        "/api/v1/" + slug + "/play/sessions/" + current.id + "/rematch",
        {},
        token,
      );
      enter(data);
      toast.success("已开新对局！先后手互换");
    } catch (e) {
      toast.error("再来一局失败：" + (e.message || "未知错误"));
    }
  }, [slug, token, enter]);

  const leave = useCallback(async () => {
    const current = sessRef.current;
    if (current) {
      try {
        await post("/api/v1/" + slug + "/play/sessions/" + current.id + "/leave", {}, token);
      } catch (e) {
        /* gone */
      }
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
    const current = sessRef.current;
    if (!current) return;
    if (!window.confirm("确定认输？对局将立即结束。")) return;
    try {
      const data = await post(
        "/api/v1/" + slug + "/play/sessions/" + current.id + "/leave",
        {},
        token,
      );
      setOver({ winner: data.winner, cause: "resigned" });
      bump();
    } catch (e) {
      toast.error("操作失败：" + (e.message || "未知错误"));
    }
  }, [slug, token, bump]);

  const addCmd = () => {
    if (selUnit === null) {
      toast.warning("先在棋盘上点选己方单位");
      return;
    }
    if (cmdIdx === null) {
      toast.warning("选择一条指令");
      return;
    }
    const entry = [selUnit, cmdIdx, dirIdx];
    if (cmdIdx === 4 || cmdIdx === 5) entry.push(unitType);
    setPending((items) => [...items, entry]);
    setSelUnit(null);
    setCmdIdx(null);
    bump();
  };

  const onCellClick = (x, y) => {
    if (submitted) {
      toast.info("本回合已提交，等待对手…");
      return;
    }
    const current = stateRef.current;
    const unit = (current && current.units || []).find((item) => item.x === x && item.y === y);
    if (unit && unit.owner === myOwner) {
      setSelUnit(unit.id);
      setCmdIdx(null);
      bump();
    } else if (unit) {
      toast.info("这是对手单位");
    }
  };

  const submit = useCallback(async () => {
    const current = sessRef.current;
    if (!current || current.status !== "active" || submitted) return;
    let action;
    if (actionType === "choice") {
      if (chosen === null) {
        toast.warning("先选择一个动作");
        return;
      }
      action = chosen;
    } else {
      if (pending.length === 0) toast.warning("先构建指令（可提交空回合）");
      action = pending;
    }
    try {
      const data = await post(
        "/api/v1/" + slug + "/play/sessions/" + current.id + "/actions",
        { actions: action },
        token,
      );
      stateRef.current = data.state;
      if (data.advanced) {
        setSubmitted(false);
        setChosen(null);
        setPending([]);
        toast.success("双方已提交，回合推进！");
      } else {
        setSubmitted(true);
        toast.info("已提交，等待对手…");
      }
      if (data.done) setOver({ winner: data.winner, cause: data.cause });
      bump();
    } catch (e) {
      toast.error("提交失败：" + (e.message || "未知错误"));
    }
  }, [slug, token, submitted, chosen, pending, actionType, bump]);

  const poll = useCallback(async () => {
    const current = sessRef.current;
    if (!current || (current.status !== "waiting" && current.status !== "active")) return;
    try {
      const data = await getJson("/api/v1/" + slug + "/play/sessions/" + current.id, token);
      const next = { ...data.session, side: data.side ?? current.side };
      const tickBefore = current.state && current.state.tick;
      sessRef.current = next;
      stateRef.current = next.state;
      if (submitted && next.state && next.state.tick !== tickBefore) {
        setSubmitted(false);
        setChosen(null);
      }
      if (next.status === "finished" && current.status !== "finished") {
        setOver({ winner: next.winner, cause: next.cause });
      }
      try {
        const chatData = await getJson(
          "/api/v1/" + slug + "/play/sessions/" + current.id + "/chat?since=" + chatSinceRef.current,
          token,
        );
        if (chatData.messages && chatData.messages.length) {
          chatSinceRef.current = chatData.next_since;
          setChat((prev) => [...prev, ...chatData.messages]);
        }
      } catch (e) {
        /* chat optional */
      }
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
    const timer = setInterval(poll, POLL_MS);
    return () => clearInterval(timer);
  }, [hasSess, poll]);

  const sessionParam = searchParams.get("session");
  useEffect(() => {
    if (sessionParam) setTab("play");
    if (!user || !token || !sessionParam || hasSess) return undefined;
    getJson("/api/v1/" + slug + "/play/sessions/" + sessionParam, token)
      .then((data) => {
        if (!data.side) {
          toast.warning("你不是该对局的玩家（仅观战）");
          return;
        }
        enter(data);
      })
      .catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionParam, user, token, slug, hasSess]);

  useEffect(() => {
    if (searchParams.get("create") === "1" && user && !hasSess) {
      setTab("find");
      const timer = setTimeout(() => createRoom("casual", "public"), 400);
      return () => clearTimeout(timer);
    }
    if (searchParams.get("join") === "1" && user) {
      setTab("find");
      setTimeout(() => joinInputRef.current && joinInputRef.current.focus(), 60);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams, user, hasSess]);

  const sendChat = useCallback(async () => {
    const text = chatText.trim();
    const current = sessRef.current;
    if (!text || !current) return;
    try {
      await post(
        "/api/v1/" + slug + "/play/sessions/" + current.id + "/chat",
        { text },
        token,
      );
      setChatText("");
      const data = await getJson(
        "/api/v1/" + slug + "/play/sessions/" + current.id + "/chat?since=" + chatSinceRef.current,
        token,
      );
      if (data.messages && data.messages.length) {
        chatSinceRef.current = data.next_since;
        setChat((prev) => [...prev, ...data.messages]);
      }
    } catch (e) {
      toast.error("发送失败：" + (e.message || "未知错误"));
    }
  }, [slug, chatText, token]);

  const copyInvite = async () => {
    try {
      await navigator.clipboard.writeText(sessRef.current.invite);
      setCopyOk(true);
      toast.success("邀请码已复制");
    } catch (e) {
      toast.warning("手动复制：" + sessRef.current.invite);
    }
  };

  const gameTitle = (meta && (meta.title || slug)) || slug;

  if (loadErr) {
    return (
      <>
        <div className="lab-page-head">
          <div className="lab-page-head__copy">
            <h1 className="lab-h1">对战</h1>
            <p className="lab-subtitle">{String(slug).toUpperCase()} · PvP</p>
          </div>
        </div>
        <div className="lab-card">
          <ErrorNote error={new Error(loadErr)} />
          <div style={{ marginTop: 12 }}>
            <LinkButton variant="outline" size="sm" href={`/games/${slug}`}>
              <ArrowLeft size={13} />
              去单机页
            </LinkButton>
          </div>
        </div>
      </>
    );
  }

  if (!meta || !info) return <Loading label="加载对战环境" />;

  const chatPanel = (
    <ChatPanel
      user={user}
      chat={chat}
      chatText={chatText}
      setChatText={setChatText}
      sendChat={sendChat}
    />
  );

  return (
    <>
      <div className="lab-page-head">
        <div className="lab-page-head__copy">
          <div className="lab-row" style={{ gap: 10, flexWrap: "wrap" }}>
            <h1 className="lab-h1">{gameTitle} · 对战</h1>
            <Chip>PVP</Chip>
            <Pill tone="neutral">验证支线</Pill>
          </div>
          <p className="lab-subtitle">
            本游戏内的房间 / 匹配 / 聊天 / 排行榜 · 不设跨游戏对战中心
          </p>
        </div>
        <div className="lab-page-head__actions">
          <LinkButton variant="outline" size="sm" href={`/games/${slug}`}>
            <ArrowLeft size={13} />
            单机
          </LinkButton>
          <LinkButton variant="outline" size="sm" href={`/environments/${slug}`}>
            <Gamepad2 size={13} />
            环境详情
          </LinkButton>
        </div>
      </div>

      {!user && authReady ? (
        <div className="lab-card">
          <EmptyState
            icon={<Swords size={18} />}
            title="PvP 需要登录"
            desc="联网对战、房间聊天与 ELO 积分都需要一个账号；游客可以去单机页试玩环境。"
            action={
              <div className="lab-row" style={{ gap: 10, justifyContent: "center" }}>
                <Button variant="primary" onClick={() => openAuth("login")}>
                  登录 / 注册
                </Button>
                <LinkButton variant="outline" href={`/games/${slug}`}>
                  去单机页
                </LinkButton>
              </div>
            }
          />
        </div>
      ) : user ? (
        <>
          <Tabs
            items={[
              { key: "find", label: "找对手" },
              { key: "play", label: "对局" },
              { key: "rank", label: "排行榜" },
            ]}
            value={tab}
            onChange={setTab}
          />

          {tab === "find" ? (
            <div className="pvp-find">
              <div className="lab-card pvp-rooms">
                <div className="lab-card__head">
                  <span className="lab-card__title">PUBLIC ROOMS</span>
                  <span className="lab-mono" style={{ fontSize: 8 }}>5s 刷新</span>
                </div>
                <div className="pvp-toolbar">
                  <label className="pvp-search">
                    <Search size={13} />
                    <input
                      placeholder="搜索房主 / 邀请码"
                      value={roomSearch}
                      onChange={(event) => setRoomSearch(event.target.value)}
                    />
                  </label>
                  <Button variant="primary" size="sm" onClick={() => createRoom("casual", "public")}>
                    <Users size={13} />
                    创建公开房间
                  </Button>
                </div>
                {filteredRooms.length === 0 ? (
                  <EmptyState
                    icon={<Home size={15} />}
                    title={rooms.length ? "没有匹配的房间" : "暂无等待中的公开房间"}
                    desc="创建一个，等对手加入，或去右侧快速匹配。"
                  />
                ) : (
                  <div>
                    <div className="pvp-rank-head">
                      <span style={{ flex: "1 1 auto" }}>房主</span>
                      <span style={{ width: 46 }}>模式</span>
                      <span style={{ width: 70 }}>邀请码</span>
                      <span style={{ width: 54 }}>创建</span>
                      <span style={{ width: 56, textAlign: "right" }}>操作</span>
                    </div>
                    {filteredRooms.map((room) => (
                      <div className="pvp-room-row" key={room.id}>
                        <span className="pvp-room-host">
                          {room.host_id === user.id ? `${room.host}（我）` : room.host}
                        </span>
                        <span style={{ width: 46 }}>
                          <Pill tone={room.mode === "ranked" ? "amber" : "green"}>
                            {room.mode === "ranked" ? "排位" : "练习"}
                          </Pill>
                        </span>
                        <span className="pvp-room-invite" style={{ width: 70 }}>{room.invite}</span>
                        <span className="pvp-room-time" style={{ width: 54 }}>
                          {relativeTime(room.created_at)}
                        </span>
                        <span style={{ width: 56, textAlign: "right" }}>
                          {room.host_id === user.id ? (
                            <Pill tone="neutral">我的房间</Pill>
                          ) : (
                            <Button size="xs" onClick={() => joinPublicRoom(room.id)}>
                              加入
                            </Button>
                          )}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
                <p className="pvp-note">
                  公开房间任何人可见可加入；排位局结算 ELO，练习局不计分。列表每 5 秒刷新。
                </p>
              </div>

              <div className="pvp-sidecol">
                <div className="lab-card" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                  <div className="lab-card__head">
                    <span className="lab-card__title">QUICK MATCH</span>
                    <Zap size={12} style={{ color: "var(--lab-text-3)" }} />
                  </div>
                  <p className="pvp-note">
                    一键排队，系统按 ELO 撮合旗鼓相当的对手；等得越久，积分范围放宽越大。
                  </p>
                  <div className="env-filters">
                    {["ranked", "casual"].map((mode) => (
                      <button
                        key={mode}
                        type="button"
                        className={`env-filter${quickMode === mode ? " is-active" : ""}`}
                        disabled={Boolean(queue)}
                        onClick={() => setQuickMode(mode)}
                      >
                        {mode === "ranked" ? "排位 ranked" : "练习 casual"}
                      </button>
                    ))}
                  </div>
                  {queue ? (
                    <div className="pvp-queue">
                      <span className="pvp-queue__line">
                        <span className="lab-spinner" aria-hidden="true" />
                        排队中… 位置 #{queue.position} · 已等待 {queue.wait_seconds} 秒
                      </span>
                      <Button variant="danger" size="sm" onClick={cancelQueue}>
                        取消匹配
                      </Button>
                    </div>
                  ) : (
                    <Button variant="primary" size="sm" onClick={startQueue}>
                      <Zap size={13} />
                      开始匹配
                    </Button>
                  )}
                </div>

                <div className="lab-card" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                  <div className="lab-card__head">
                    <span className="lab-card__title">INVITE CODE</span>
                    <Ticket size={12} style={{ color: "var(--lab-text-3)" }} />
                  </div>
                  <div className="pvp-mode-row">
                    {["casual", "ranked"].map((mode) => (
                      <button
                        key={mode}
                        type="button"
                        className={`env-filter${createMode === mode ? " is-active" : ""}`}
                        onClick={() => setCreateMode(mode)}
                      >
                        {mode === "casual" ? "练习" : "排位"}
                      </button>
                    ))}
                  </div>
                  <Button variant="outline" size="sm" onClick={() => createRoom(null, "private")}>
                    <Users size={13} />
                    创建私有房间
                  </Button>
                  <hr className="lab-rule" />
                  <span className="lab-mono" style={{ fontSize: 8 }}>输入朋友的 6 位邀请码</span>
                  <div className="lab-row" style={{ gap: 8 }}>
                    <input
                      ref={joinInputRef}
                      className="lab-input"
                      style={{ height: 36, textTransform: "uppercase", letterSpacing: "0.16em" }}
                      placeholder="邀请码"
                      value={joinCode}
                      maxLength={6}
                      onChange={(event) => setJoinCode(event.target.value.toUpperCase())}
                      onKeyDown={(event) => {
                        if (event.key === "Enter") joinRoom();
                      }}
                    />
                    <Button variant="primary" size="sm" onClick={joinRoom}>
                      加入
                    </Button>
                  </div>
                </div>
              </div>
            </div>
          ) : null}

          {tab === "play" ? (
            !sess ? (
              <div className="lab-card">
                <EmptyState
                  icon={<Gamepad2 size={17} />}
                  title="还没有对局"
                  desc="去「找对手」加入公开房间、快速匹配，或输入邀请码开房。"
                  action={
                    <Button variant="primary" size="sm" onClick={() => setTab("find")}>
                      去找对手
                    </Button>
                  }
                />
              </div>
            ) : waiting ? (
              <div className="pvp-wait-layout">
                <div className="lab-card">
                  <div className="lab-card__head">
                    <span className="lab-card__title">WAITING FOR OPPONENT</span>
                    <Pill tone="amber" dot>
                      等待中
                    </Pill>
                  </div>
                  <div className="pvp-invite-box">
                    <span className="pvp-invite-code">{sess.invite}</span>
                    <div className="lab-row" style={{ gap: 6 }}>
                      <Pill tone={sess.mode === "ranked" ? "amber" : "green"}>
                        {sess.mode === "ranked" ? "排位 ranked（计 ELO）" : "练习 casual（不计分）"}
                      </Pill>
                      <Pill tone="neutral">
                        {sess.visibility === "public" ? "公开房间" : "私有房间"}
                      </Pill>
                    </div>
                    <span className="pvp-note">把邀请码发给朋友，或等待公开房间被加入。</span>
                    <div className="lab-row" style={{ gap: 8 }}>
                      <Button variant="primary" size="sm" onClick={copyInvite}>
                        <Copy size={12} />
                        {copyOk ? "已复制 ✓" : "复制邀请码"}
                      </Button>
                      <Button
                        variant="danger"
                        size="sm"
                        onClick={() => {
                          if (window.confirm("确定取消房间？")) leave();
                        }}
                      >
                        取消房间
                      </Button>
                    </div>
                  </div>
                </div>
                {chatPanel}
              </div>
            ) : (
              <div className="pvp-play-layout">
                <div style={{ display: "flex", flexDirection: "column", gap: 14, minWidth: 0 }}>
                  <div className="pvp-board-card">
                    <div className="pvp-board-head">
                      <span className="envp-preview__live">
                        <i aria-hidden="true" /> LIVE MATCH
                      </span>
                      <div className="lab-row" style={{ gap: 8 }}>
                        <Pill tone="green" dot>
                          对局中
                        </Pill>
                        <span className="lab-mono" style={{ fontSize: 8 }}>TICK {state ? state.tick : 0}</span>
                      </div>
                    </div>
                    <BoardFrame fitKey={`${slug}:${state ? state.tick : ""}`} minHeight={620}>
                      <UgBoard
                        state={state}
                        meta={meta}
                        onCellClick={actionType === "unit" ? onCellClick : null}
                      />
                    </BoardFrame>
                    <div className="pvp-players">
                      {(sess.players || []).map((player) => (
                        <Pill
                          key={player.side}
                          tone={player.side === "p0" ? "cyan" : "violet"}
                          dot
                        >
                          {SIDE_NAME[player.side]} {player.name || "…"}
                          {player.submitted ? " · 已提交" : ""}
                        </Pill>
                      ))}
                      <span className="lab-grow" />
                      <span className="lab-mono" style={{ fontSize: 8 }}>
                        我的阵营：{SIDE_NAME[mySide]}
                      </span>
                    </div>
                  </div>

                  <div className="pvp-controls">
                    {actionType === "choice" ? (
                      <div className="lab-row" style={{ gap: 8, flexWrap: "wrap" }}>
                        {choices.map((choice, index) => (
                          <button
                            key={index}
                            type="button"
                            className={`play-choice${chosen === index ? " is-active" : ""}`}
                            disabled={submitted}
                            onClick={() => setChosen(index)}
                          >
                            {choice}
                          </button>
                        ))}
                      </div>
                    ) : (
                      <>
                        <span className="pvp-cmd-label">指令</span>
                        <div className="pvp-cmds">
                          {Object.entries(actions).map(([key, label]) => (
                            <button
                              key={key}
                              type="button"
                              className={`pvp-cmd${cmdIdx === Number(key) ? " is-active" : ""}`}
                              disabled={submitted}
                              onClick={() => setCmdIdx(Number(key))}
                            >
                              {key} {String(label).split("(")[0]}
                            </button>
                          ))}
                        </div>
                        <span className="pvp-cmd-label">方向 / 类型</span>
                        <div className="lab-row" style={{ gap: 6, flexWrap: "wrap" }}>
                          {Object.entries(dirs).map(([key, label]) => (
                            <button
                              key={key}
                              type="button"
                              className={`pvp-cmd${dirIdx === Number(key) ? " is-active" : ""}`}
                              disabled={submitted}
                              onClick={() => setDirIdx(Number(key))}
                            >
                              {label}
                            </button>
                          ))}
                          {cmdIdx === 4 || cmdIdx === 5 ? (
                            <select
                              className="lab-select"
                              style={{ height: 30, width: 130, fontSize: 11 }}
                              value={unitType}
                              disabled={submitted}
                              onChange={(event) => setUnitType(event.target.value)}
                            >
                              {UNIT_TYPES.map((type) => (
                                <option key={type} value={type}>
                                  {type}
                                </option>
                              ))}
                            </select>
                          ) : null}
                          <Button size="xs" variant="outline" disabled={submitted} onClick={addCmd}>
                            <Plus size={11} />
                            添加指令
                          </Button>
                        </div>
                        {pending.length > 0 ? (
                          <div className="pvp-pending">
                            {pending.map((entry, index) => (
                              <button
                                key={`${entry.join("-")}-${index}`}
                                type="button"
                                className="pvp-pending-chip"
                                title="点击移除"
                                onClick={() =>
                                  setPending((items) => items.filter((_, position) => position !== index))
                                }
                              >
                                #{entry[0]} {String(actions[entry[1]] || entry[1]).split("(")[0]}
                                {dirs[entry[2]] ? " " + dirs[entry[2]] : ""}
                                {entry[3] ? " " + entry[3] : ""} ✕
                              </button>
                            ))}
                          </div>
                        ) : null}
                        {selectedUnit ? (
                          <span className="pvp-note">
                            已选单位 #{selectedUnit.id}（{selectedUnit.type}）@ ({selectedUnit.x},{selectedUnit.y})
                          </span>
                        ) : null}
                      </>
                    )}
                    <div className="lab-row" style={{ gap: 8, flexWrap: "wrap" }}>
                      <Button variant="primary" size="sm" disabled={submitted} onClick={submit}>
                        <Send size={12} />
                        {submitted ? "已提交，等待对手…" : "提交本回合"}
                      </Button>
                      <Button variant="danger" size="sm" onClick={resign}>
                        <Flag size={12} />
                        认输
                      </Button>
                      <span className="lab-grow" />
                      <span className="pvp-note">
                        {actionType === "choice" ? "选择动作后提交；双方都提交后回合推进。" : "可提交空回合。"}
                      </span>
                    </div>
                  </div>
                </div>

                <aside className="pvp-play-side">
                  <div className="lab-card" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                    <div className="lab-card__head">
                      <span className="lab-card__title">MATCH INFO</span>
                      <Pill tone={sess.mode === "ranked" ? "amber" : "green"}>{sess.mode === "ranked" ? "排位" : "练习"}</Pill>
                    </div>
                    <div className="play-kv">
                      <span>我的阵营</span>
                      <b>{SIDE_NAME[mySide]}</b>
                    </div>
                    <div className="play-kv">
                      <span>当前 Tick</span>
                      <b>{state ? state.tick : 0}</b>
                    </div>
                    <div className="play-kv">
                      <span>房间</span>
                      <b>{sess.visibility === "public" ? "公开" : "私有"}</b>
                    </div>
                    {myRating ? (
                      <div className="play-kv">
                        <span>我的 ELO</span>
                        <b>{Math.round(myRating.rating)}（{myRating.games} 局）</b>
                      </div>
                    ) : null}
                    <span className="lab-mono" style={{ fontSize: 7.5 }}>
                      对局实时轮询 2s · 刷新/断线后可继续（服务重启后内存会话失效）
                    </span>
                  </div>
                  {chatPanel}
                </aside>
              </div>
            )
          ) : null}

          {tab === "rank" ? (
            <div className="lab-card" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <div className="lab-card__head">
                <div className="lab-row" style={{ gap: 8 }}>
                  <span className="lab-card__title">LEADERBOARD</span>
                  <span className="lab-mono" style={{ fontSize: 8 }}>{String(slug).toUpperCase()}</span>
                </div>
                {myRating ? (
                  <Pill tone="amber">
                    <Trophy size={9} /> 我的 ELO：{Math.round(myRating.rating)}（{myRating.games} 局）
                  </Pill>
                ) : null}
              </div>
              <div className="env-filters">
                <button
                  type="button"
                  className={`env-filter${boardScope === "total" ? " is-active" : ""}`}
                  onClick={() => setBoardScope("total")}
                >
                  总榜（ELO）
                </button>
                <button
                  type="button"
                  className={`env-filter${boardScope === "weekly" ? " is-active" : ""}`}
                  onClick={() => setBoardScope("weekly")}
                >
                  周榜（近 7 天）
                </button>
              </div>
              {boardScope === "total" ? (
                ratings.length === 0 ? (
                  <EmptyState icon={<Trophy size={15} />} title="还没有人打过 PvP" desc="来开第一局吧。" />
                ) : (
                  <div>
                    <div className="pvp-rank-head">
                      <span className="pvp-rank-pos">排名</span>
                      <span style={{ flex: "1 1 auto" }}>玩家</span>
                      <span className="pvp-rank-num">ELO</span>
                      <span className="pvp-rank-num">局数</span>
                      <span className="pvp-rank-num">胜</span>
                    </div>
                    {ratings.map((rating, index) => (
                      <div
                        className={`pvp-rank-row${rating.user_id === user.id ? " is-me" : ""}`}
                        key={rating.user_id}
                      >
                        <span className={`pvp-rank-pos${index === 0 ? " is-top" : ""}`}>
                          #{index + 1}
                        </span>
                        <span className="pvp-rank-name">
                          {rating.user_id === user.id ? `${rating.name}（我）` : rating.name}
                        </span>
                        <span className="pvp-rank-num">{Math.round(rating.rating)}</span>
                        <span className="pvp-rank-num">{rating.games}</span>
                        <span className="pvp-rank-num">{rating.wins}</span>
                      </div>
                    ))}
                    <p className="pvp-note" style={{ marginTop: 10 }}>
                      每局 ranked 按 ELO 结算（K=32，起始 1200）；练习与模型对战不计分。
                    </p>
                  </div>
                )
              ) : weeklyBoard.length === 0 ? (
                <EmptyState icon={<Trophy size={15} />} title="本周还没有人打 PvP" />
              ) : (
                <div>
                  <div className="pvp-rank-head">
                    <span className="pvp-rank-pos">排名</span>
                    <span style={{ flex: "1 1 auto" }}>玩家</span>
                    <span className="pvp-rank-num">胜场</span>
                    <span className="pvp-rank-num">局数</span>
                    <span className="pvp-rank-num">XP</span>
                  </div>
                  {weeklyBoard.map((row, index) => (
                    <div
                      className={`pvp-rank-row${row.user_id === user.id ? " is-me" : ""}`}
                      key={row.user_id}
                    >
                      <span className={`pvp-rank-pos${index === 0 ? " is-top" : ""}`}>
                        #{index + 1}
                      </span>
                      <span className="pvp-rank-name">
                        {row.user_id === user.id ? `${row.name}（我）` : row.name}
                      </span>
                      <span className="pvp-rank-num">{row.wins}</span>
                      <span className="pvp-rank-num">{row.games}</span>
                      <span className="pvp-rank-num">{row.xp}</span>
                    </div>
                  ))}
                  <p className="pvp-note" style={{ marginTop: 10 }}>
                    按最近 7 天胜场数排名（同胜场看局数，再看本周 XP）。
                  </p>
                </div>
              )}
              <span className="pvp-note">
                模型 vs 模型对抗在 <Link className="lab-link lab-link--lime" to="/models">模型工作台</Link> 发起。
              </span>
            </div>
          ) : null}
        </>
      ) : null}

      {over ? (
        <Modal
          title={
            over.winner === (mySide === "p0" ? 0 : 1)
              ? "你赢了！"
              : over.winner === null || over.winner === undefined
                ? "平局"
                : "你输了"
          }
          onClose={() => setOver(null)}
        >
          <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            <p className="lab-subtitle" style={{ margin: 0 }}>
              {over.cause === "timeout" && "一方连续超时被判负"}
              {over.cause === "resigned" && "一方认输，对局结束"}
              {!over.cause && "对局结束"}
            </p>
            <div className="lab-modal__actions">
              <Button variant="outline" onClick={rematch}>
                再来一局（互换先后手）
              </Button>
              <Button variant="primary" onClick={leave}>
                返回找对手
              </Button>
            </div>
          </div>
        </Modal>
      ) : null}
    </>
  );
}
