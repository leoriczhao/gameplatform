import "./admin.css";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  Activity,
  BrainCircuit,
  ChevronLeft,
  ChevronRight,
  Flag,
  Gamepad2,
  LayoutDashboard,
  Megaphone,
  RefreshCw,
  Shield,
  Swords,
  UsersRound,
} from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../AuthContext.jsx";
import { useLabAuth } from "../AuthDialog.jsx";
import { getJson, post } from "../api.js";
import {
  Button,
  Card,
  EmptyState,
  ErrorNote,
  Loading,
  Modal,
  Pill,
  Tabs,
} from "../ui.jsx";
import { gameLabel, kindLabel, statusLabel, statusTone } from "../format.js";

/* 管理后台（v1.0-d）：看板/公告/用户/模型/举报/对局/UGC；非 admin 显示 403。
   行为与旧 pages/Admin.jsx 一致：同一组 admin API、同样的操作与确认语义，
   渲染层换成 Lab UI（侧栏外壳由 LabShell 提供）。 */

const PAGE_SIZE = 15;

function usePaged(items, pageSize = PAGE_SIZE) {
  const [page, setPage] = useState(1);
  const list = Array.isArray(items) ? items : [];
  const pageCount = Math.max(1, Math.ceil(list.length / pageSize));
  const safePage = Math.min(page, pageCount);
  const start = (safePage - 1) * pageSize;
  return {
    items: list.slice(start, start + pageSize),
    page: safePage,
    pageCount,
    total: list.length,
    setPage: (next) => setPage(Math.min(Math.max(1, next), pageCount)),
  };
}

function pageList(page, pageCount) {
  const out = [];
  for (let p = 1; p <= pageCount; p += 1) {
    if (p === 1 || p === pageCount || Math.abs(p - page) <= 1) out.push(p);
    else if (out[out.length - 1] !== "…") out.push("…");
  }
  return out;
}

function Pager({ page, pageCount, total, onChange }) {
  if (pageCount <= 1) return null;
  return (
    <div className="adm-pager">
      <span className="adm-pager__meta">
        共 {total} 条 · 第 {page} / {pageCount} 页
      </span>
      <div className="adm-pager__btns">
        <button
          type="button"
          className="adm-pager__btn"
          disabled={page <= 1}
          onClick={() => onChange(page - 1)}
          aria-label="上一页"
        >
          <ChevronLeft size={13} />
        </button>
        {pageList(page, pageCount).map((p, index) =>
          p === "…" ? (
            <span className="adm-pager__gap" key={"gap-" + index}>…</span>
          ) : (
            <button
              type="button"
              key={p}
              className={"adm-pager__btn" + (p === page ? " is-active" : "")}
              aria-current={p === page ? "page" : undefined}
              onClick={() => onChange(p)}
            >
              {p}
            </button>
          ),
        )}
        <button
          type="button"
          className="adm-pager__btn"
          disabled={page >= pageCount}
          onClick={() => onChange(page + 1)}
          aria-label="下一页"
        >
          <ChevronRight size={13} />
        </button>
      </div>
    </div>
  );
}

function Stat({ label, value }) {
  return (
    <div className="adm-stat">
      <span className="adm-stat__label">{label}</span>
      <b className="adm-stat__value">{value == null ? "—" : value}</b>
    </div>
  );
}

function AdminTable({ head, children }) {
  return (
    <div className="adm-table-wrap">
      <table className="adm-table">
        <thead>
          <tr>
            {head.map((cell) => {
              const item = typeof cell === "string" ? { label: cell } : cell;
              return (
                <th key={item.label} className={item.align === "right" ? "is-right" : ""}>
                  {item.label}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

function Panel({ title, mono, children }) {
  return (
    <Card className="adm-panel">
      <div className="lab-card__head">
        <span className="lab-card__title">{title}</span>
        {mono ? <span className="lab-mono" style={{ fontSize: 8 }}>{mono}</span> : null}
      </div>
      <div className="adm-panel__body">{children}</div>
    </Card>
  );
}

function DataState({ loading, error, empty, title, desc, onRetry, children }) {
  if (loading) return <Loading label="载入数据" />;
  if (error) return <ErrorNote error={error} onRetry={onRetry} />;
  if (empty) {
    return (
      <EmptyState
        icon={<Activity size={16} />}
        title={title}
        desc={desc}
      />
    );
  }
  return children;
}

function EmptyPanel({ title, desc }) {
  return (
    <EmptyState icon={<Activity size={16} />} title={title} desc={desc} />
  );
}

/* 资源缩略图：草稿资源需鉴权，img 标签带不了 header，故 fetch → blob URL。 */
function AssetThumb({ url, token, name }) {
  const [src, setSrc] = useState(null);
  const [err, setErr] = useState(false);
  useEffect(() => {
    let alive = true;
    let obj = null;
    fetch(url, { headers: token ? { Authorization: "Bearer " + token } : {} })
      .then((r) => {
        if (!r.ok) throw new Error(String(r.status));
        return r.blob();
      })
      .then((b) => {
        if (!alive) return;
        obj = URL.createObjectURL(b);
        setSrc(obj);
      })
      .catch(() => {
        if (alive) setErr(true);
      });
    return () => {
      alive = false;
      if (obj) URL.revokeObjectURL(obj);
    };
  }, [url, token]);
  if (err) return <span className="adm-thumb-fallback">{name}（不可读）</span>;
  if (!src) return <span className="adm-thumb-fallback">{name}…</span>;
  return <img src={src} alt={name} title={name} className="adm-thumb" />;
}

const EMPTY_DATA = {
  dashboard: null,
  users: [],
  models: [],
  reports: [],
  matches: [],
  ugc: [],
  ugcAll: [],
  anns: [],
};

const UGC_TONE = { published: "green", banned: "red", pending: "amber", draft: "neutral" };
const REPORT_TONE = { open: "amber", resolved: "green", dismissed: "neutral" };

export default function Admin() {
  const { user, token, authReady } = useAuth();
  const { openAuth } = useLabAuth();
  const [tab, setTab] = useState("dashboard");
  const [data, setData] = useState(EMPTY_DATA);
  const [errors, setErrors] = useState({});
  const [loading, setLoading] = useState(false);
  const [annBody, setAnnBody] = useState("");
  const [annErr, setAnnErr] = useState("");
  const [rview, setRview] = useState(null);
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  const pagedAnns = usePaged(data.anns);
  const pagedUsers = usePaged(data.users);
  const pagedModels = usePaged(data.models);
  const pagedReports = usePaged(data.reports);
  const pagedMatches = usePaged(data.matches);
  const pagedUgc = usePaged(data.ugc);
  const pagedUgcAll = usePaged(data.ugcAll);

  const loadAll = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    const jobs = [
      ["dashboard", "/api/v1/admin/dashboard", (d) => d],
      ["users", "/api/v1/admin/users", (d) => d.users || []],
      ["models", "/api/v1/admin/models", (d) => d.models || []],
      ["reports", "/api/v1/admin/reports", (d) => d.reports || []],
      ["matches", "/api/v1/admin/matches", (d) => d.matches || []],
      ["ugc", "/api/v1/admin/ugc", (d) => d.games || []],
      ["ugcAll", "/api/v1/admin/ugc?status=all", (d) => d.games || []],
      ["anns", "/api/v1/admin/announcements", (d) => d.items || []],
    ];
    const next = { ...EMPTY_DATA };
    const nextErrors = {};
    await Promise.all(
      jobs.map(async ([key, url, pick]) => {
        try {
          const payload = await getJson(url, token);
          next[key] = pick(payload);
        } catch (e) {
          nextErrors[key] = e;
        }
      }),
    );
    if (!alive.current) return;
    setData(next);
    setErrors(nextErrors);
    setLoading(false);
  }, [token]);

  useEffect(() => {
    if (user && user.role === "admin") loadAll();
  }, [user, loadAll]);

  const act = async (fn, ok) => {
    try {
      await fn();
      toast.success(ok);
      loadAll();
    } catch (e) {
      toast.error("操作失败：" + e.message);
    }
  };

  const openRenderer = async (g) => {
    try {
      const d = await getJson("/api/v1/admin/ugc/" + g.id + "/renderer", token);
      setRview({ game: g, ...d });
    } catch (e) {
      toast.error("读取渲染器失败：" + e.message);
    }
  };

  const toggleRenderer = (g, enabled) =>
    act(
      () => post("/api/v1/admin/ugc/" + g.id + "/renderer", { enabled }, token),
      enabled ? "已开启沙箱渲染器" : "已关闭沙箱渲染器",
    );

  const assetList = (g) => Object.values((g && g.meta && g.meta.assets) || {});
  const assetUrlOf = (g, file) =>
    "/api/ugc/assets/" + encodeURIComponent(g.slug) + "/" + encodeURIComponent(g.version) + "/" + file;

  const createAnn = async () => {
    if (!annBody.trim()) {
      setAnnErr("输入公告内容");
      return;
    }
    setAnnErr("");
    await act(
      () => post("/api/v1/admin/announcements", { body: annBody }, token),
      "公告已发布",
    );
    setAnnBody("");
  };

  if (!authReady) return <Loading label="校验登录状态" />;

  if (!user) {
    return (
      <>
        <div className="lab-page-head">
          <div className="lab-page-head__copy">
            <h1 className="lab-h1">管理后台</h1>
            <p className="lab-subtitle">公告 · 用户封禁 · 模型下架 · 举报处理 · 数据看板（v1.0-d）</p>
          </div>
        </div>
        <Card>
          <EmptyState
            icon={<Shield size={18} />}
            title="请先登录管理员账号"
            desc="管理后台需要 admin 权限。"
            action={
              <Button variant="primary" onClick={() => openAuth("login")}>
                登录管理账号
              </Button>
            }
          />
        </Card>
      </>
    );
  }

  if (user.role !== "admin") {
    return (
      <>
        <div className="lab-page-head">
          <div className="lab-page-head__copy">
            <h1 className="lab-h1">管理后台</h1>
            <p className="lab-subtitle">该页面仅平台管理员可访问。</p>
          </div>
        </div>
        <Card>
          <EmptyState
            icon={<Shield size={18} />}
            title="403 · 没有管理员权限"
            desc="当前账号不是管理员。如需开通，请联系平台维护者。"
            action={
              <Link className="lab-btn lab-btn--primary lab-btn--sm" to="/">
                回大厅
              </Link>
            }
          />
        </Card>
      </>
    );
  }

  const tabItems = [
    { key: "dashboard", label: (<><LayoutDashboard size={13} /> 看板</>) },
    { key: "anns", label: (<><Megaphone size={13} /> 公告</>) },
    { key: "users", label: (<><UsersRound size={13} /> 用户</>) },
    { key: "models", label: (<><BrainCircuit size={13} /> 模型</>) },
    { key: "reports", label: (<><Flag size={13} /> 举报</>) },
    { key: "matches", label: (<><Swords size={13} /> 对局</>) },
    { key: "ugc", label: (<><Gamepad2 size={13} /> UGC 审核</>) },
  ];

  const reloadDashboard = () => loadAll();

  return (
    <>
      <div className="lab-page-head">
        <div className="lab-page-head__copy">
          <h1 className="lab-h1">管理后台</h1>
          <p className="lab-subtitle">
            公告 · 用户封禁 · 模型下架 · 举报处理 · 数据看板（v1.0-d）
          </p>
        </div>
        <div className="lab-page-head__actions">
          <Button variant="outline" size="sm" onClick={loadAll} disabled={loading}>
            <RefreshCw size={13} />
            {loading ? "刷新中…" : "刷新"}
          </Button>
          <Link className="lab-btn lab-btn--ghost lab-btn--sm" to="/">
            <Gamepad2 size={13} />
            大厅
          </Link>
        </div>
      </div>

      <Tabs items={tabItems} value={tab} onChange={setTab} />

      {tab === "dashboard" ? (
        <Panel title="PLATFORM DASHBOARD" mono="v1.0-d">
          {loading && !data.dashboard ? (
            <Loading label="载入看板" />
          ) : errors.dashboard ? (
            <ErrorNote error={errors.dashboard} onRetry={reloadDashboard} />
          ) : data.dashboard ? (
            <div className="adm-stats">
              <Stat label="注册用户" value={data.dashboard.users_total} />
              <Stat label="24h 新注册" value={data.dashboard.users_new_24h} />
              <Stat label="24h 活跃（DAU 代理）" value={data.dashboard.dau_24h} />
              <Stat label="进行中会话" value={data.dashboard.active_sessions} />
              <Stat label="PvP 对局总数" value={data.dashboard.matches_total} />
              <Stat label="24h 对局" value={data.dashboard.matches_24h} />
              <Stat label="活跃模型" value={data.dashboard.models_active} />
              <Stat label="待处理举报" value={data.dashboard.reports_open} />
            </div>
          ) : (
            <EmptyPanel title="暂无看板数据" desc="刷新后再试；若持续为空，请检查服务端 admin API。" />
          )}
        </Panel>
      ) : null}

      {tab === "anns" ? (
        <Panel title="ANNOUNCEMENTS" mono={data.anns.length + " 条"}>
          <div className="adm-composer">
            <input
              className="lab-input"
              placeholder="全站公告内容（≤300 字符）"
              maxLength={300}
              value={annBody}
              onChange={(e) => setAnnBody(e.target.value)}
              aria-label="公告内容"
            />
            <Button variant="primary" onClick={createAnn}>发布公告</Button>
          </div>
          {annErr ? <p className="adm-form-error">{annErr}</p> : null}
          <DataState
            loading={loading && data.anns.length === 0}
            error={errors.anns}
            empty={data.anns.length === 0}
            title="还没有公告"
            desc="发布一条全站公告，所有访客都会在大厅看到。"
            onRetry={reloadDashboard}
          >
            <>
              <AdminTable head={["ID", "内容", "状态", "时间", "操作"]}>
                {pagedAnns.items.map((r) => (
                  <tr key={r.id}>
                    <td className="adm-cell-mono">{r.id}</td>
                    <td>{r.body}</td>
                    <td>
                      {r.active
                        ? <Pill tone="green">生效中</Pill>
                        : <Pill tone="neutral">已停用</Pill>}
                    </td>
                    <td>{new Date(r.created_at * 1000).toLocaleString("zh-CN", { hour12: false })}</td>
                    <td>
                      <Button
                        size="xs"
                        variant="outline"
                        onClick={() =>
                          act(
                            () =>
                              post(
                                "/api/v1/admin/announcements/" + r.id + "/active",
                                { status: r.active ? "off" : "on" },
                                token,
                              ),
                            r.active ? "已停用" : "已启用",
                          )
                        }
                      >
                        {r.active ? "停用" : "启用"}
                      </Button>
                    </td>
                  </tr>
                ))}
              </AdminTable>
              <Pager
                page={pagedAnns.page}
                pageCount={pagedAnns.pageCount}
                total={pagedAnns.total}
                onChange={pagedAnns.setPage}
              />
            </>
          </DataState>
        </Panel>
      ) : null}

      {tab === "users" ? (
        <Panel title="USERS" mono={data.users.length + " 个账号"}>
          <DataState
            loading={loading && data.users.length === 0}
            error={errors.users}
            empty={data.users.length === 0}
            title="还没有用户"
            desc="注册用户会出现在这里，可执行封禁 / 解封。"
            onRetry={reloadDashboard}
          >
            <>
              <AdminTable
                head={["ID", "用户名", "昵称", "角色", "状态", { label: "XP", align: "right" }, "操作"]}
              >
                {pagedUsers.items.map((r) => (
                  <tr key={r.id}>
                    <td className="adm-cell-mono">{r.id}</td>
                    <td><b>{r.username}</b></td>
                    <td>{r.nickname}</td>
                    <td>
                      {r.role === "admin"
                        ? <Pill tone="amber">admin</Pill>
                        : <Pill tone="neutral">user</Pill>}
                    </td>
                    <td>
                      <Pill tone={r.status === "active" ? "green" : "red"}>{r.status}</Pill>
                    </td>
                    <td className="is-right">{r.xp}</td>
                    <td>
                      {r.role === "admin" ? (
                        <span className="adm-muted">—</span>
                      ) : r.status === "active" ? (
                        <Button
                          size="xs"
                          variant="danger"
                          onClick={() => {
                            if (!window.confirm("封禁 @" + r.username + "？封禁后无法登录")) return;
                            act(
                              () =>
                                post(
                                  "/api/v1/admin/users/" + r.id + "/status",
                                  { status: "banned" },
                                  token,
                                ),
                              "已封禁",
                            );
                          }}
                        >
                          封禁
                        </Button>
                      ) : (
                        <Button
                          size="xs"
                          onClick={() =>
                            act(
                              () =>
                                post(
                                  "/api/v1/admin/users/" + r.id + "/status",
                                  { status: "active" },
                                  token,
                                ),
                              "已解封",
                            )
                          }
                        >
                          解封
                        </Button>
                      )}
                    </td>
                  </tr>
                ))}
              </AdminTable>
              <Pager
                page={pagedUsers.page}
                pageCount={pagedUsers.pageCount}
                total={pagedUsers.total}
                onChange={pagedUsers.setPage}
              />
            </>
          </DataState>
        </Panel>
      ) : null}

      {tab === "models" ? (
        <Panel title="MODELS" mono={data.models.length + " 个模型"}>
          <DataState
            loading={loading && data.models.length === 0}
            error={errors.models}
            empty={data.models.length === 0}
            title="还没有模型"
            desc="用户上传的 ONNX 模型会出现在这里，可下架 / 恢复。"
            onRetry={reloadDashboard}
          >
            <>
              <AdminTable head={["ID", "名称", "游戏", "拥有者", "状态", "操作"]}>
                {pagedModels.items.map((r) => (
                  <tr key={r.id}>
                    <td className="adm-cell-mono">{r.id}</td>
                    <td>{r.name}</td>
                    <td>{r.game}</td>
                    <td>{r.owner}</td>
                    <td>
                      <Pill tone={r.status === "active" ? "green" : "red"}>{r.status}</Pill>
                    </td>
                    <td>
                      {r.status === "active" ? (
                        <Button
                          size="xs"
                          variant="danger"
                          onClick={() => {
                            if (!window.confirm("下架模型 #" + r.id + "？")) return;
                            act(
                              () =>
                                post(
                                  "/api/v1/admin/models/" + r.id + "/status",
                                  { status: "banned" },
                                  token,
                                ),
                              "已下架",
                            );
                          }}
                        >
                          下架
                        </Button>
                      ) : (
                        <Button
                          size="xs"
                          onClick={() =>
                            act(
                              () =>
                                post(
                                  "/api/v1/admin/models/" + r.id + "/status",
                                  { status: "active" },
                                  token,
                                ),
                              "已恢复",
                            )
                          }
                        >
                          恢复
                        </Button>
                      )}
                    </td>
                  </tr>
                ))}
              </AdminTable>
              <Pager
                page={pagedModels.page}
                pageCount={pagedModels.pageCount}
                total={pagedModels.total}
                onChange={pagedModels.setPage}
              />
            </>
          </DataState>
        </Panel>
      ) : null}

      {tab === "reports" ? (
        <Panel title="REPORTS" mono={data.reports.length + " 条举报"}>
          <DataState
            loading={loading && data.reports.length === 0}
            error={errors.reports}
            empty={data.reports.length === 0}
            title="没有举报"
            desc="举报队列为空，暂时不需要处理。"
            onRetry={reloadDashboard}
          >
            <>
              <AdminTable head={["ID", "举报人", "目标", "理由", "状态", "操作"]}>
                {pagedReports.items.map((r) => (
                  <tr key={r.id}>
                    <td className="adm-cell-mono">{r.id}</td>
                    <td>{r.reporter}</td>
                    <td>{r.target_type + " #" + r.target_id}</td>
                    <td>{r.reason}</td>
                    <td>
                      <Pill tone={REPORT_TONE[r.status] || "neutral"}>{r.status}</Pill>
                    </td>
                    <td>
                      {r.status === "open" ? (
                        <div className="adm-actions">
                          <Button
                            size="xs"
                            onClick={() =>
                              act(
                                () =>
                                  post(
                                    "/api/v1/admin/reports/" + r.id + "/status",
                                    { status: "resolved" },
                                    token,
                                  ),
                                "已处理",
                              )
                            }
                          >
                            已处理
                          </Button>
                          <Button
                            size="xs"
                            variant="outline"
                            onClick={() =>
                              act(
                                () =>
                                  post(
                                    "/api/v1/admin/reports/" + r.id + "/status",
                                    { status: "dismissed" },
                                    token,
                                  ),
                                "已驳回",
                              )
                            }
                          >
                            驳回
                          </Button>
                        </div>
                      ) : (
                        <span className="adm-muted">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </AdminTable>
              <Pager
                page={pagedReports.page}
                pageCount={pagedReports.pageCount}
                total={pagedReports.total}
                onChange={pagedReports.setPage}
              />
            </>
          </DataState>
        </Panel>
      ) : null}

      {tab === "matches" ? (
        <Panel title="MATCHES" mono={data.matches.length + " 场"}>
          <DataState
            loading={loading && data.matches.length === 0}
            error={errors.matches}
            empty={data.matches.length === 0}
            title="还没有对局"
            desc="PvP 与模型对战落库后会出现在这里。"
            onRetry={reloadDashboard}
          >
            <>
              <AdminTable head={["ID", "游戏", "类型", "对阵", "状态", "时间"]}>
                {pagedMatches.items.map((m) => (
                  <tr key={m.id}>
                    <td className="adm-cell-mono">{m.id}</td>
                    <td>{gameLabel(m.game)}</td>
                    <td>{kindLabel(m.kind)}</td>
                    <td>
                      {m.kind === "pvp"
                        ? (m.players || []).map((p) => p.name).join(" vs ")
                        : (m.models || []).map((x) => x.name).join(" vs ")}
                    </td>
                    <td>
                      <Pill tone={statusTone(m.status)}>{statusLabel(m.status)}</Pill>
                    </td>
                    <td>{new Date(m.created_at * 1000).toLocaleString("zh-CN", { hour12: false })}</td>
                  </tr>
                ))}
              </AdminTable>
              <Pager
                page={pagedMatches.page}
                pageCount={pagedMatches.pageCount}
                total={pagedMatches.total}
                onChange={pagedMatches.setPage}
              />
            </>
          </DataState>
        </Panel>
      ) : null}

      {tab === "ugc" ? (
        <div className="adm-ugc-stack">
          <Panel title="UGC · 待审核（PENDING）" mono={data.ugc.length + " 个"}>
            <DataState
              loading={loading && data.ugc.length === 0}
              error={errors.ugc}
              empty={data.ugc.length === 0}
              title="审核队列为空"
              desc="新提交的 UGC 游戏会进入这里等待人工审核。"
              onRetry={reloadDashboard}
            >
              <>
                <AdminTable head={["ID", "标题", "作者", "版本", "冒烟", "渲染器", "操作"]}>
                  {pagedUgc.items.map((g) => (
                    <tr key={g.id}>
                      <td className="adm-cell-mono">{g.id}</td>
                      <td>{g.title}</td>
                      <td>{g.author}</td>
                      <td>v{g.version}</td>
                      <td>
                        {g.smoke && g.smoke.ok
                          ? <Pill tone="green">通过</Pill>
                          : <Pill tone="red">失败</Pill>}
                      </td>
                      <td>
                        {g.meta && g.meta.renderer ? (
                          <Button size="xs" variant="outline" onClick={() => openRenderer(g)}>
                            查看
                          </Button>
                        ) : (
                          <span className="adm-muted">—</span>
                        )}
                      </td>
                      <td>
                        <div className="adm-actions">
                          <Button
                            size="xs"
                            onClick={() =>
                              act(
                                () => post("/api/v1/admin/ugc/" + g.id + "/approve", {}, token),
                                "已通过并发布",
                              )
                            }
                          >
                            通过
                          </Button>
                          <Button
                            size="xs"
                            variant="outline"
                            onClick={() => {
                              const note = window.prompt("驳回意见（必填）");
                              if (note && note.trim()) {
                                act(
                                  () =>
                                    post(
                                      "/api/v1/admin/ugc/" + g.id + "/reject",
                                      { note: note.trim() },
                                      token,
                                    ),
                                  "已驳回",
                                );
                              }
                            }}
                          >
                            驳回
                          </Button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </AdminTable>
                <Pager
                  page={pagedUgc.page}
                  pageCount={pagedUgc.pageCount}
                  total={pagedUgc.total}
                  onChange={pagedUgc.setPage}
                />
              </>
            </DataState>
          </Panel>

          <Panel title="UGC · 全部游戏" mono={data.ugcAll.length + " 个"}>
            <DataState
              loading={loading && data.ugcAll.length === 0}
              error={errors.ugcAll}
              empty={data.ugcAll.length === 0}
              title="还没有 UGC 游戏"
              desc="作者上传游戏包后，这里会列出全部状态与渲染器开关。"
              onRetry={reloadDashboard}
            >
              <>
                <AdminTable head={["ID", "标题", "作者", "状态", "渲染器", "操作"]}>
                  {pagedUgcAll.items.map((g) => (
                    <tr key={g.id}>
                      <td className="adm-cell-mono">{g.id}</td>
                      <td>{g.title}</td>
                      <td>{g.author}</td>
                      <td>
                        <Pill tone={UGC_TONE[g.status] || "neutral"}>{g.status}</Pill>
                      </td>
                      <td>
                        {g.meta && g.meta.renderer ? (
                          <div className="adm-actions">
                            <Pill tone={g.renderer_enabled ? "green" : "neutral"}>
                              {g.renderer_enabled ? "已开启" : "未开启"}
                            </Pill>
                            <Button size="xs" variant="outline" onClick={() => openRenderer(g)}>
                              源码
                            </Button>
                            <Button
                              size="xs"
                              variant={g.renderer_enabled ? "outline" : "primary"}
                              onClick={() => toggleRenderer(g, !g.renderer_enabled)}
                            >
                              {g.renderer_enabled ? "关闭" : "开启"}
                            </Button>
                          </div>
                        ) : (
                          <span className="adm-muted">—</span>
                        )}
                      </td>
                      <td>
                        {g.status === "banned" ? (
                          <Button
                            size="xs"
                            onClick={() =>
                              act(
                                () => post("/api/v1/admin/ugc/" + g.id + "/unban", {}, token),
                                "已恢复为草稿",
                              )
                            }
                          >
                            恢复
                          </Button>
                        ) : g.status === "published" ? (
                          <Button
                            size="xs"
                            variant="danger"
                            onClick={() =>
                              act(
                                () => post("/api/v1/admin/ugc/" + g.id + "/ban", {}, token),
                                "已下架",
                              )
                            }
                          >
                            下架
                          </Button>
                        ) : (
                          <span className="adm-muted">—</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </AdminTable>
                <Pager
                  page={pagedUgcAll.page}
                  pageCount={pagedUgcAll.pageCount}
                  total={pagedUgcAll.total}
                  onChange={pagedUgcAll.setPage}
                />
              </>
            </DataState>
          </Panel>
        </div>
      ) : null}

      {rview ? (
        <Modal title={"渲染器审核 · " + (rview.game ? rview.game.title : "")} wide onClose={() => setRview(null)}>
          <p className="lab-subtitle adm-modal-desc">
            沙箱渲染器默认关闭。开启后前端会用 opaque-origin iframe + Worker 运行下面的代码
            （无 DOM/无网络/无凭证，超时自动降级），请人工核对资源与代码内容。
          </p>
          <div className="adm-renderer">
            <span className="adm-kicker">资源（{assetList(rview.game).length}）</span>
            <div className="adm-thumbs">
              {assetList(rview.game).map((a) => (
                <AssetThumb
                  key={a.file}
                  url={assetUrlOf(rview.game, a.file)}
                  token={token}
                  name={a.file}
                />
              ))}
              {!assetList(rview.game).length ? (
                <span className="adm-muted">无</span>
              ) : null}
            </div>
            <span className="adm-kicker">
              渲染器源码{rview.renderer ? "（" + rview.renderer.size + " B）" : ""}
            </span>
            {rview.renderer ? (
              <pre className="adm-code">{rview.renderer.source}</pre>
            ) : (
              <p className="lab-subtitle">该版本没有自定义渲染器。</p>
            )}
          </div>
          <div className="lab-modal__actions">
            <Button variant="outline" onClick={() => setRview(null)}>关闭</Button>
          </div>
        </Modal>
      ) : null}
    </>
  );
}
