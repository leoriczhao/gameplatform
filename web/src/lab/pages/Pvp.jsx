import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import "./play.css";
import "./pvp.css";
import { toast } from "sonner";
import {
  ArrowLeft,
  Gamepad2,
  Plus,
  RefreshCw,
  Search,
  Swords,
  Ticket,
  Users,
  X,
  Zap,
} from "lucide-react";
import { useAuth } from "../../AuthContext.jsx";
import { useLabAuth } from "../AuthDialog.jsx";
import { del, getJson, post, useGames } from "../api.js";
import { relativeTime } from "../format.js";
import {
  Button,
  Chip,
  CopyButton,
  EmptyState,
  ErrorNote,
  Field,
  LinkButton,
  Loading,
  Modal,
  Pill,
} from "../ui.jsx";

const ROOM_POLL_MS = 5000;   // 大厅房间列表刷新间隔（秒）
const QUEUE_POLL_MS = 2000;  // 快速匹配：匹配状态轮询间隔（docs/design/17 §7.7）

// v2 错误码 → 人话（docs/design/17 §5.1）。入座失败是最常见的分支，
// 这里都按 code 分开提示，避免把 bad_invite 和 seat_taken 混成一句"失败"。
const CODE_TEXT = {
  bad_invite: "邀请码不正确，请向房主确认",
  seat_taken: "座位已经被占用，换一个房间试试",
  not_joinable: "房间已开始或已结束",
  already_seated: "你已经在这个房间里了",
  no_such_seat: "该房间没有可加入的座位",
  not_live: "房间不存在或已结束",
  not_found: "房间不存在或已结束",
  bad_seats: "座位配置无效",
  bad_mode: "模式不可用",
  bad_visibility: "可见性不可用",
  bad_queue: "无法进入匹配队列，请稍后重试",
  too_many_matches: "同时进行的对局过多，请先结束其他对局",
  no_pvp: "该游戏不支持人类对战",
  unknown_game: "游戏不存在或未公开",
  login_required: "请先登录",
};

function errorText(error, fallback = "操作失败") {
  if (!error) return fallback;
  return (error.code && CODE_TEXT[error.code]) || error.message || fallback;
}

// 允许从邀请链接（/m/{id}）或裸房间 id 里解析出 uid
function parseRoomId(raw) {
  const text = String(raw || "").trim();
  if (!text) return "";
  const hit = text.match(/\/m\/([A-Za-z0-9_-]+)/);
  if (hit) return hit[1];
  return text.split(/[?#]/)[0].replace(/\/+$/, "");
}

export default function Pvp() {
  const { slug } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const { user, token, authReady } = useAuth();
  const { openAuth } = useLabAuth();
  const gamesQuery = useGames();
  const loggedIn = Boolean(user) && user.role !== "guest";

  const [rooms, setRooms] = useState([]);
  const [roomsLoading, setRoomsLoading] = useState(true);
  const [roomsError, setRoomsError] = useState(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [roomFilter, setRoomFilter] = useState("");
  const [createMode, setCreateMode] = useState("casual");
  const [createVisibility, setCreateVisibility] = useState("public");
  const [creating, setCreating] = useState(false);
  const [inviteRoom, setInviteRoom] = useState(null);
  const [joinInput, setJoinInput] = useState("");
  const [joinCode, setJoinCode] = useState("");
  const [joining, setJoining] = useState(false);
  const [queueMode, setQueueMode] = useState("casual");
  const [queue, setQueue] = useState(null);
  const [queueBusy, setQueueBusy] = useState(false);

  const mountedRef = useRef(true);
  const queueRef = useRef(null);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);
  useEffect(() => {
    queueRef.current = queue;
  }, [queue]);

  const isUgc = location.pathname.startsWith("/games/ugc/");
  const playPath = isUgc ? `/games/ugc/${slug}` : `/games/${slug}`;
  const catalog = (gamesQuery.data && gamesQuery.data.games) || [];
  const game = catalog.find((item) => item.id === slug) || null;
  const meta = (game && game.meta) || {};
  const gameTitle = meta.title || (game && game.name) || slug;
  const pvpEnabled = Boolean(game && game.pvp_enabled);

  const ensureLogin = () => {
    if (authReady && !loggedIn) {
      openAuth("login");
      return false;
    }
    return true;
  };

  // 房间列表：v2 lobby 只返回 waiting 的公开房；轮询 5s。
  // 组件卸载 / slug 变化时 abort 掉在途请求并清定时器，避免 __setState on unmounted__。
  useEffect(() => {
    if (!loggedIn) return undefined;
    let alive = true;
    const controller = new AbortController();
    let timer = null;
    const load = async () => {
      try {
        const data = await getJson(
          `/api/v2/matches?game=${encodeURIComponent(slug)}`,
          token,
          controller.signal,
        );
        if (!alive) return;
        setRooms(data.rooms || []);
        setRoomsError(null);
        setRoomsLoading(false);
      } catch (e) {
        if (!alive || (e && e.name === "AbortError")) return;
        setRoomsError(e);
        setRoomsLoading(false);
      }
      if (alive) timer = setTimeout(load, ROOM_POLL_MS);
    };
    load();
    return () => {
      alive = false;
      controller.abort();
      if (timer) clearTimeout(timer);
    };
  }, [slug, token, loggedIn, reloadKey]);

  // 快速匹配状态轮询：2s 一次；出现 match_id 就进舞台。
  // 依赖只放"是否在队列中"这个布尔，避免位置更新时重置定时器。
  const queued = Boolean(queue && queue.queued);
  useEffect(() => {
    if (!queued) return undefined;
    let alive = true;
    let timer = null;
    const tick = async () => {
      try {
        const status = await getJson(
          `/api/v2/${encodeURIComponent(slug)}/matchmaking/status`,
          token,
        );
        if (!alive) return;
        if (status.matched && status.match_id) {
          setQueue(null);
          toast.success("匹配成功，正在进入对局…");
          navigate(`/m/${status.match_id}`);
          return;
        }
        if (!status.queued) {
          setQueue(null);
          toast.warning("已不在匹配队列中（可能超时或被取消）");
          return;
        }
        setQueue(status);
      } catch (e) {
        if (!alive) return;
        if (e && e.status === 401) {
          setQueue(null);
          toast.error("登录已过期，请重新登录");
          openAuth("login");
          return;
        }
        /* 瞬时网络错误：保持队列，下个周期重试 */
      }
      if (alive) timer = setTimeout(tick, QUEUE_POLL_MS);
    };
    timer = setTimeout(tick, QUEUE_POLL_MS);
    return () => {
      alive = false;
      if (timer) clearTimeout(timer);
    };
  }, [queued, slug, token, navigate, openAuth]);

  // 离开页面时如果还在排队，尽量取消，避免人不在时被配对出一局
  useEffect(
    () => () => {
      if (queueRef.current && queueRef.current.queued) {
        del(`/api/v2/${encodeURIComponent(slug)}/matchmaking/queue`, token).catch(() => {});
      }
    },
    [slug, token],
  );

  const createRoom = async () => {
    if (!ensureLogin()) return;
    setCreating(true);
    try {
      const view = await post(
        "/api/v2/matches",
        {
          game: slug,
          seats: [
            { seat: "p0", occupant: "me", controller: { type: "human" } },
            { seat: "p1", occupant: null, controller: { type: "human" } },
          ],
          mode: createMode,
          visibility: createVisibility,
        },
        token,
      );
      if (!mountedRef.current) return;
      if (view.visibility === "private" && view.invite) {
        // 私有房先把邀请码/链接给房主（stage 的等待卡也会显示，但这里更早可见）
        setInviteRoom({ id: view.id, invite: view.invite, mode: view.mode });
      } else {
        toast.success("房间已创建，等待对手入座");
        navigate(`/m/${view.id}`);
      }
    } catch (e) {
      if (mountedRef.current) toast.error(errorText(e, "创建房间失败"));
    } finally {
      if (mountedRef.current) setCreating(false);
    }
  };

  // 统一入口：id 来自房间列表按钮，或从输入框解析；invite 只在私有房需要
  const joinRoom = async ({ id = null, code = null } = {}) => {
    if (!ensureLogin()) return;
    const roomId = id || parseRoomId(joinInput);
    if (!roomId) {
      toast.warning("请输入房间 ID 或邀请链接");
      return;
    }
    const invite = (code === null || code === undefined ? joinCode : code).trim();
    setJoining(true);
    try {
      await post(
        `/api/v2/matches/${encodeURIComponent(roomId)}/seats/p1/join`,
        invite ? { invite } : {},
        token,
      );
      if (!mountedRef.current) return;
      toast.success("已加入房间");
      navigate(`/m/${roomId}`);
    } catch (e) {
      if (!mountedRef.current) return;
      // 已经坐在房里（比如重复点自己的房间）：直接进舞台即可
      if (e && e.code === "already_seated") {
        navigate(`/m/${roomId}`);
        return;
      }
      toast.error(errorText(e, "加入房间失败"));
    } finally {
      if (mountedRef.current) setJoining(false);
    }
  };

  const startQueue = async () => {
    if (!ensureLogin()) return;
    setQueueBusy(true);
    try {
      const status = await post(
        `/api/v2/${encodeURIComponent(slug)}/matchmaking/queue`,
        { mode: queueMode },
        token,
      );
      if (!mountedRef.current) return;
      if (status.matched && status.match_id) {
        toast.success("已匹配到对手，进入对局");
        navigate(`/m/${status.match_id}`);
        return;
      }
      setQueue(status);
      toast.info("已进入匹配队列，等待对手…");
    } catch (e) {
      if (mountedRef.current) toast.error(errorText(e, "进入匹配队列失败"));
    } finally {
      if (mountedRef.current) setQueueBusy(false);
    }
  };

  const cancelQueue = async () => {
    try {
      await del(`/api/v2/${encodeURIComponent(slug)}/matchmaking/queue`, token);
    } catch (e) {
      /* 已经不在队列里也没关系 */
    }
    setQueue(null);
    toast.info("已取消匹配");
  };

  const closeInvite = () => {
    if (!inviteRoom) return;
    const id = inviteRoom.id;
    setInviteRoom(null);
    navigate(`/m/${id}`);
  };

  if (!authReady) return <Loading label="连接账号服务" />;
  if (gamesQuery.loading && !gamesQuery.data) return <Loading label="加载对战环境" />;

  if (gamesQuery.error) {
    return (
      <>
        <div className="lab-page-head">
          <div className="lab-page-head__copy">
            <h1 className="lab-h1">对战大厅</h1>
            <p className="lab-subtitle">{String(slug || "").toUpperCase()} · PvP</p>
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

  const head = (
    <div className="lab-page-head">
      <div className="lab-page-head__copy">
        <div className="lab-row" style={{ gap: 10, flexWrap: "wrap" }}>
          <h1 className="lab-h1">{gameTitle} · 对战大厅</h1>
          <Chip>PVP</Chip>
          {meta.version ? <Chip>v{meta.version}</Chip> : null}
          <Pill tone="neutral" dot>
            房间 / 快速匹配 / 邀请码
          </Pill>
        </div>
        <p className="lab-subtitle">
          创建房间或快速匹配后进入 <span className="lab-mono">/m/:id</span> 舞台；聊天与对局操作都在舞台里。
        </p>
      </div>
      <div className="lab-page-head__actions">
        <LinkButton variant="outline" size="sm" href={playPath}>
          <ArrowLeft size={13} />
          单机准备
        </LinkButton>
        <LinkButton variant="outline" size="sm" href={`/environments/${slug}`}>
          <Gamepad2 size={13} />
          环境详情
        </LinkButton>
      </div>
    </div>
  );

  if (!pvpEnabled) {
    return (
      <>
        {head}
        <div className="lab-card">
          <EmptyState
            icon={<Swords size={16} />}
            title="该游戏不支持人类对战"
            desc="game.yaml 未开启 pvp.enabled；可以回到单机准备页与 AI 或自己的模型对局。"
            action={
              <LinkButton variant="primary" size="sm" href={playPath}>
                <Gamepad2 size={13} />
                去单机准备
              </LinkButton>
            }
          />
        </div>
      </>
    );
  }

  if (!loggedIn) {
    return (
      <>
        {head}
        <div className="lab-card">
          <EmptyState
            icon={<Swords size={18} />}
            title="对战大厅需要登录"
            desc="创建/加入房间、快速匹配与 ELO 积分都需要账号；游客可以先回单机准备页查看环境。"
            action={
              <div className="lab-row" style={{ gap: 10, justifyContent: "center" }}>
                <Button variant="primary" onClick={() => openAuth("login")}>
                  登录 / 注册
                </Button>
                <LinkButton variant="outline" href={playPath}>
                  去单机准备
                </LinkButton>
              </div>
            }
          />
        </div>
      </>
    );
  }

  const keyword = roomFilter.trim().toLowerCase();
  const filteredRooms = rooms.filter((room) => {
    if (!keyword) return true;
    return (room.host || "").toLowerCase().includes(keyword)
      || String(room.id).toLowerCase().includes(keyword);
  });
  const inviteLink = inviteRoom
    ? `${typeof window !== "undefined" ? window.location.origin : ""}/m/${inviteRoom.id}`
    : "";

  return (
    <>
      {head}

      <div className="pvp-find">
        <div className="pvp-rooms">
          <div className="lab-card" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <div className="lab-card__head">
              <span className="lab-card__title">ROOMS</span>
              <div className="lab-row" style={{ gap: 8 }}>
                <span className="lab-mono" style={{ fontSize: 8 }}>
                  {rooms.length} WAITING
                </span>
                <Button variant="ghost" size="xs" onClick={() => setReloadKey((n) => n + 1)}>
                  <RefreshCw size={11} />
                  刷新
                </Button>
              </div>
            </div>
            <div className="pvp-search">
              <Search size={12} />
              <input
                value={roomFilter}
                placeholder="按房主或房间 ID 过滤…"
                onChange={(event) => setRoomFilter(event.target.value)}
              />
            </div>
            {roomsError ? (
              <ErrorNote error={roomsError} onRetry={() => setReloadKey((n) => n + 1)} />
            ) : null}
            {roomsLoading ? (
              <Loading label="载入房间" />
            ) : filteredRooms.length === 0 ? (
              <EmptyState
                icon={<Users size={15} />}
                title="还没有等待中的公开房间"
                desc="创建公开房间，或直接用右侧快速匹配。"
              />
            ) : (
              filteredRooms.map((room) => {
                const mine = user && room.host_id != null && room.host_id === user.id;
                return (
                  <div className="pvp-room-row" key={room.id}>
                    <span className="pvp-room-host" title={room.id}>
                      {room.host || "匿名"}
                      <span className="lab-mono" style={{ fontSize: 7.5, marginLeft: 6 }}>
                        #{String(room.id).slice(0, 6)}
                      </span>
                    </span>
                    <Pill tone={room.mode === "ranked" ? "amber" : "neutral"}>
                      {room.mode === "ranked" ? "排位" : "休闲"}
                    </Pill>
                    <span className="pvp-room-time">{relativeTime(room.created_at)}</span>
                    {mine ? (
                      <Button
                        variant="outline"
                        size="xs"
                        onClick={() => navigate(`/m/${room.id}`)}
                      >
                        打开
                      </Button>
                    ) : (
                      <Button
                        variant="outline"
                        size="xs"
                        disabled={joining}
                        onClick={() => joinRoom({ id: room.id, code: "" })}
                      >
                        加入
                      </Button>
                    )}
                  </div>
                );
              })
            )}
          </div>
        </div>

        <div className="pvp-sidecol">
          <div className="lab-card" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <div className="lab-card__head">
              <span className="lab-card__title">CREATE ROOM</span>
              <Plus size={12} style={{ color: "var(--lab-text-3)" }} />
            </div>
            <Field label="模式">
              <select
                className="lab-select"
                value={createMode}
                onChange={(event) => setCreateMode(event.target.value)}
              >
                <option value="casual">休闲 casual（不计 ELO）</option>
                <option value="ranked">排位 ranked（计 ELO）</option>
              </select>
            </Field>
            <Field label="可见性">
              <select
                className="lab-select"
                value={createVisibility}
                onChange={(event) => setCreateVisibility(event.target.value)}
              >
                <option value="public">公开 public（出现在房间列表）</option>
                <option value="private">私有 private（凭邀请码加入）</option>
              </select>
            </Field>
            <Button variant="primary" onClick={createRoom} disabled={creating}>
              <Swords size={13} />
              {creating ? "创建中…" : "创建房间"}
            </Button>
            <span className="pvp-note">
              创建后进入 <span className="lab-mono">/m/:id</span> 等待对手；私有房会生成 6 位邀请码。
            </span>
          </div>

          <div className="lab-card" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <div className="lab-card__head">
              <span className="lab-card__title">JOIN BY INVITE</span>
              <Ticket size={12} style={{ color: "var(--lab-text-3)" }} />
            </div>
            <Field label="房间 ID 或邀请链接">
              <input
                className="lab-input"
                value={joinInput}
                placeholder="/m/abc123 或 abc123"
                onChange={(event) => setJoinInput(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") joinRoom({});
                }}
              />
            </Field>
            <Field label="邀请码（私有房）" hint="公开房留空">
              <input
                className="lab-input"
                value={joinCode}
                maxLength={6}
                placeholder="6 位邀请码"
                onChange={(event) => setJoinCode(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") joinRoom({});
                }}
              />
            </Field>
            <Button variant="outline" onClick={() => joinRoom({})} disabled={joining}>
              {joining ? "加入中…" : "加入房间"}
            </Button>
            <span className="pvp-note">
              有邀请链接时直接粘贴；私有房还需要房主另外告诉你的邀请码。
            </span>
          </div>

          <div className="lab-card" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <div className="lab-card__head">
              <span className="lab-card__title">QUICK MATCH</span>
              <Zap size={12} style={{ color: "var(--lab-text-3)" }} />
            </div>
            {queued ? (
              <div className="pvp-queue">
                <div className="pvp-queue__line">
                  <span className="lab-spinner" aria-hidden="true" />
                  正在匹配 · 第 {queue.position != null ? queue.position : "—"} 位
                </div>
                <div className="pvp-queue__line">
                  模式 {queue.mode === "ranked" ? "排位" : "休闲"} · 已等待{" "}
                  {queue.wait_seconds != null ? queue.wait_seconds : 0}s
                </div>
                <Button variant="outline" size="sm" onClick={cancelQueue}>
                  <X size={12} />
                  取消匹配
                </Button>
              </div>
            ) : (
              <>
                <Field label="匹配模式">
                  <select
                    className="lab-select"
                    value={queueMode}
                    onChange={(event) => setQueueMode(event.target.value)}
                  >
                    <option value="casual">休闲 casual</option>
                    <option value="ranked">排位 ranked</option>
                  </select>
                </Field>
                <Button variant="primary" onClick={startQueue} disabled={queueBusy}>
                  <Zap size={13} />
                  {queueBusy ? "进入队列…" : "快速匹配"}
                </Button>
                <span className="pvp-note">每 2 秒查询一次匹配状态；匹配成功后自动进入舞台。</span>
              </>
            )}
          </div>
        </div>
      </div>

      {inviteRoom ? (
        <Modal title="私有房间已创建" onClose={closeInvite}>
          <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            <p className="lab-subtitle" style={{ margin: 0 }}>
              把邀请码和链接发给对手；对手在大厅粘贴链接并填写邀请码即可入座。
            </p>
            <div className="pvp-invite-box">
              <span className="pvp-invite-code">{inviteRoom.invite}</span>
              <div className="lab-row" style={{ gap: 10 }}>
                <CopyButton text={inviteRoom.invite} label="复制邀请码" />
                <CopyButton text={inviteLink} label="复制链接" />
              </div>
              <span className="lab-mono" style={{ fontSize: 8 }}>{inviteLink}</span>
            </div>
            <div className="lab-modal__actions">
              <Button variant="primary" onClick={closeInvite}>
                进入对局
              </Button>
            </div>
          </div>
        </Modal>
      ) : null}
    </>
  );
}
