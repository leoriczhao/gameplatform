import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  ShieldIcon, Gamepad2Icon, MegaphoneIcon, UsersRoundIcon, BrainCircuitIcon,
  FlagIcon, SwordsIcon, LayoutDashboardIcon,
} from "lucide-react";
import { useAuth } from "../AuthContext.jsx";
import { getJson, post } from "../api.js";
import { toast } from "sonner";
import { Button } from "../components/ui/button.jsx";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card.jsx";
import { Badge } from "../components/ui/badge.jsx";
import { Input } from "../components/ui/input.jsx";
import { Label } from "../components/ui/label.jsx";
import { Stat } from "../components/ui/stat.jsx";
import { Alert } from "../components/ui/alert.jsx";
import { Confirm } from "../components/ui/confirm.jsx";
import { PageHeader } from "../components/ui/page-header.jsx";
import { EmptyState } from "../components/ui/empty-state.jsx";
import { Spinner } from "../components/ui/spinner.jsx";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "../components/ui/tabs.jsx";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../components/ui/dialog.jsx";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "../components/ui/table.jsx";
import { Pagination, usePaged } from "../components/ui/pagination.jsx";

/* 资源缩略图：草稿资源需鉴权，img 标签带不了 header，故 fetch → blob URL。 */
function AssetThumb({ url, token, name }) {
  const [src, setSrc] = useState(null);
  const [err, setErr] = useState(false);
  useEffect(() => {
    let alive = true;
    let obj = null;
    fetch(url, { headers: token ? { Authorization: `Bearer ${token}` } : {} })
      .then((r) => { if (!r.ok) throw new Error(String(r.status)); return r.blob(); })
      .then((b) => { if (!alive) return; obj = URL.createObjectURL(b); setSrc(obj); })
      .catch(() => { if (alive) setErr(true); });
    return () => { alive = false; if (obj) URL.revokeObjectURL(obj); };
  }, [url, token]);
  if (err) return <span className="text-xs text-muted-foreground">{name}（不可读）</span>;
  if (!src) return <span className="text-xs text-muted-foreground">{name}…</span>;
  return <img src={src} alt={name} title={name} className="size-10 rounded border border-border bg-white object-contain" />;
}

/* 管理后台（v1.0-d）：看板/公告/用户/模型/举报/对局；非 admin 显示 403 */
export default function Admin() {
  const { user, token, authReady } = useAuth();
  const [dashboard, setDashboard] = useState(null);
  const [users, setUsers] = useState([]);
  const [models, setModels] = useState([]);
  const [reports, setReports] = useState([]);
  const [matches, setMatches] = useState([]);
  const [ugc, setUgc] = useState([]);
  const [ugcAll, setUgcAll] = useState([]);
  const [anns, setAnns] = useState([]);
  const [annBody, setAnnBody] = useState("");
  const [annErr, setAnnErr] = useState("");
  const [tab, setTab] = useState("dashboard");

  const pagedAnns = usePaged(anns, 15);
  const pagedUsers = usePaged(users, 15);
  const pagedModels = usePaged(models, 15);
  const pagedReports = usePaged(reports, 15);
  const pagedMatches = usePaged(matches, 15);
  const pagedUgc = usePaged(ugc, 15);
  const pagedUgcAll = usePaged(ugcAll, 15);

  const loadAll = useCallback(async () => {
    if (!token) return;
    try { const d = await getJson("/api/v1/admin/dashboard", token); setDashboard(d); } catch (e) {}
    try { const d = await getJson("/api/v1/admin/users", token); setUsers(d.users || []); } catch (e) {}
    try { const d = await getJson("/api/v1/admin/models", token); setModels(d.models || []); } catch (e) {}
    try { const d = await getJson("/api/v1/admin/reports", token); setReports(d.reports || []); } catch (e) {}
    try { const d = await getJson("/api/v1/admin/matches", token); setMatches(d.matches || []); } catch (e) {}
    try { const d = await getJson("/api/v1/admin/ugc", token); setUgc(d.games || []); } catch (e) {}
    try { const d = await getJson("/api/v1/admin/ugc?status=all", token); setUgcAll(d.games || []); } catch (e) {}
    try { const d = await getJson("/api/v1/admin/announcements", token); setAnns(d.items || []); } catch (e) {}
  }, [token]);

  useEffect(() => {
    if (user?.role === "admin") loadAll();
  }, [user, loadAll]);

  const act = async (fn, ok) => {
    try { await fn(); toast.success(ok); loadAll(); }
    catch (e) { toast.error(`操作失败：${e.message}`); }
  };

  /* 渲染 v2（16 §5.1）：渲染器源码/资源预览 + 开关 */
  const [rview, setRview] = useState(null);
  const openRenderer = async (g) => {
    try {
      const d = await getJson(`/api/v1/admin/ugc/${g.id}/renderer`, token);
      setRview({ game: g, ...d });
    } catch (e) {
      toast.error(`读取渲染器失败：${e.message}`);
    }
  };
  const toggleRenderer = (g, enabled) => act(
    () => post(`/api/v1/admin/ugc/${g.id}/renderer`, { enabled }, token),
    enabled ? "已开启沙箱渲染器" : "已关闭沙箱渲染器");

  const assetList = (g) => Object.values((g.meta && g.meta.assets) || {});
  const assetUrlOf = (g, file) =>
    `/api/ugc/assets/${encodeURIComponent(g.slug)}/${encodeURIComponent(g.version)}/${file}`;

  const createAnn = async () => {
    if (!annBody.trim()) { setAnnErr("输入公告内容"); return; }
    setAnnErr("");
    await act(() => post("/api/v1/admin/announcements", { body: annBody }, token),
      "公告已发布");
    setAnnBody("");
  };

  if (!user && authReady) {
    return (
      <div className="page-shell">
        <Alert variant="warning">
          <div className="font-semibold">请先登录管理员账号</div>
          <div className="text-sm opacity-90">管理后台需要 admin 权限。</div>
        </Alert>
      </div>
    );
  }
  if (user && user.role !== "admin") {
    return (
      <div className="page-shell">
        <Alert variant="destructive">
          <div className="font-semibold">403 · 没有管理员权限</div>
          <div className="text-sm opacity-90">该页面仅平台管理员可访问。</div>
          <div className="mt-3 flex gap-2">
            <Button asChild size="sm" variant="outline">
              <Link to="/">回大厅</Link>
            </Button>
          </div>
        </Alert>
      </div>
    );
  }

  return (
    <div className="page-shell">
      <PageHeader
        icon={ShieldIcon}
        title="管理后台"
        description="公告 · 用户封禁 · 模型下架 · 举报处理 · 数据看板（v1.0-d）"
        actions={(
          <div className="flex flex-wrap items-center gap-2">
            <Button asChild variant="ghost" size="sm">
              <Link to="/"><Gamepad2Icon /> 大厅</Link>
            </Button>
          </div>
        )}
      />

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList className="flex-wrap">
          <TabsTrigger value="dashboard"><LayoutDashboardIcon /> 看板</TabsTrigger>
          <TabsTrigger value="anns"><MegaphoneIcon /> 公告</TabsTrigger>
          <TabsTrigger value="users"><UsersRoundIcon /> 用户</TabsTrigger>
          <TabsTrigger value="models"><BrainCircuitIcon /> 模型</TabsTrigger>
          <TabsTrigger value="reports"><FlagIcon /> 举报</TabsTrigger>
          <TabsTrigger value="matches"><SwordsIcon /> 对局</TabsTrigger>
          <TabsTrigger value="ugc"><Gamepad2Icon /> UGC 审核</TabsTrigger>
        </TabsList>

        <TabsContent value="dashboard">
          {dashboard ? (
            <Card>
              <CardContent className="flex flex-wrap items-center gap-x-10 gap-y-5 pt-5">
                <Stat label="注册用户" value={dashboard.users_total} />
                <Stat label="24h 新注册" value={dashboard.users_new_24h} />
                <Stat label="24h 活跃（DAU 代理）" value={dashboard.dau_24h} />
                <Stat label="进行中会话" value={dashboard.active_sessions} />
                <Stat label="PvP 对局总数" value={dashboard.matches_total} />
                <Stat label="24h 对局" value={dashboard.matches_24h} />
                <Stat label="活跃模型" value={dashboard.models_active} />
                <Stat label="待处理举报" value={dashboard.reports_open} />
              </CardContent>
            </Card>
          ) : (
            <Spinner text="加载中…" />
          )}
        </TabsContent>

        <TabsContent value="anns">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">公告</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="mb-4 flex flex-wrap gap-2">
                <div className="min-w-[240px] flex-1">
                  <Label className="sr-only">公告内容</Label>
                  <Input
                    placeholder="全站公告内容（≤300 字符）"
                    maxLength={300}
                    value={annBody}
                    onChange={(e) => setAnnBody(e.target.value)}
                  />
                  {annErr && <p className="mt-1 text-sm text-red-600">{annErr}</p>}
                </div>
                <Button onClick={createAnn}>发布公告</Button>
              </div>

              {anns.length === 0 ? (
                <EmptyState title="还没有公告" />
              ) : (
                <>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-14">ID</TableHead>
                      <TableHead>内容</TableHead>
                      <TableHead className="w-24">状态</TableHead>
                      <TableHead className="w-44">时间</TableHead>
                      <TableHead className="w-24">操作</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {pagedAnns.items.map((r) => (
                      <TableRow key={r.id}>
                        <TableCell>{r.id}</TableCell>
                        <TableCell>{r.body}</TableCell>
                        <TableCell>
                          {r.active
                            ? <Badge variant="success">生效中</Badge>
                            : <Badge variant="outline">已停用</Badge>}
                        </TableCell>
                        <TableCell>
                          {new Date(r.created_at * 1000).toLocaleString("zh-CN", { hour12: false })}
                        </TableCell>
                        <TableCell>
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => act(
                              () => post(`/api/v1/admin/announcements/${r.id}/active`,
                                { status: r.active ? "off" : "on" }, token),
                              r.active ? "已停用" : "已启用")}
                          >
                            {r.active ? "停用" : "启用"}
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
                <Pagination page={pagedAnns.page} pageCount={pagedAnns.pageCount}
                  total={pagedAnns.total} onChange={pagedAnns.setPage} />
                </>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="users">
          <Card>
            <CardContent className="pt-5">
              {users.length === 0 ? (
                <EmptyState title="还没有用户" />
              ) : (
                <>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-14">ID</TableHead>
                      <TableHead>用户名</TableHead>
                      <TableHead>昵称</TableHead>
                      <TableHead className="w-20">角色</TableHead>
                      <TableHead className="w-20">状态</TableHead>
                      <TableHead className="w-20 text-right">XP</TableHead>
                      <TableHead className="w-28">操作</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {pagedUsers.items.map((r) => (
                      <TableRow key={r.id}>
                        <TableCell>{r.id}</TableCell>
                        <TableCell><b>{r.username}</b></TableCell>
                        <TableCell>{r.nickname}</TableCell>
                        <TableCell>
                          {r.role === "admin"
                            ? <Badge variant="warning">admin</Badge>
                            : <Badge variant="secondary">user</Badge>}
                        </TableCell>
                        <TableCell>
                          <Badge variant={r.status === "active" ? "success" : "destructive"}>
                            {r.status}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-right">{r.xp}</TableCell>
                        <TableCell>
                          {r.role === "admin" ? null : r.status === "active" ? (
                            <Confirm
                              title={`封禁 @${r.username}？封禁后无法登录`}
                              confirmText="封禁"
                              onConfirm={() => act(
                                () => post(`/api/v1/admin/users/${r.id}/status`,
                                  { status: "banned" }, token), "已封禁")}
                            >
                              <Button size="sm" variant="destructive">封禁</Button>
                            </Confirm>
                          ) : (
                            <Button
                              size="sm"
                              onClick={() => act(
                                () => post(`/api/v1/admin/users/${r.id}/status`,
                                  { status: "active" }, token), "已解封")}
                            >
                              解封
                            </Button>
                          )}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
                <Pagination page={pagedUsers.page} pageCount={pagedUsers.pageCount}
                  total={pagedUsers.total} onChange={pagedUsers.setPage} />
                </>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="models">
          <Card>
            <CardContent className="pt-5">
              {models.length === 0 ? (
                <EmptyState title="还没有模型" />
              ) : (
                <>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-14">ID</TableHead>
                      <TableHead>名称</TableHead>
                      <TableHead className="w-24">游戏</TableHead>
                      <TableHead>拥有者</TableHead>
                      <TableHead className="w-24">状态</TableHead>
                      <TableHead className="w-28">操作</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {pagedModels.items.map((r) => (
                      <TableRow key={r.id}>
                        <TableCell>{r.id}</TableCell>
                        <TableCell>{r.name}</TableCell>
                        <TableCell>{r.game}</TableCell>
                        <TableCell>{r.owner}</TableCell>
                        <TableCell>
                          <Badge variant={r.status === "active" ? "success" : "destructive"}>
                            {r.status}
                          </Badge>
                        </TableCell>
                        <TableCell>
                          {r.status === "active" ? (
                            <Confirm
                              title={`下架模型 #${r.id}？`}
                              confirmText="下架"
                              onConfirm={() => act(
                                () => post(`/api/v1/admin/models/${r.id}/status`,
                                  { status: "banned" }, token), "已下架")}
                            >
                              <Button size="sm" variant="destructive">下架</Button>
                            </Confirm>
                          ) : (
                            <Button
                              size="sm"
                              onClick={() => act(
                                () => post(`/api/v1/admin/models/${r.id}/status`,
                                  { status: "active" }, token), "已恢复")}
                            >
                              恢复
                            </Button>
                          )}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
                <Pagination page={pagedModels.page} pageCount={pagedModels.pageCount}
                  total={pagedModels.total} onChange={pagedModels.setPage} />
                </>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="reports">
          <Card>
            <CardContent className="pt-5">
              {reports.length === 0 ? (
                <EmptyState title="没有举报" />
              ) : (
                <>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-14">ID</TableHead>
                      <TableHead>举报人</TableHead>
                      <TableHead>目标</TableHead>
                      <TableHead>理由</TableHead>
                      <TableHead className="w-24">状态</TableHead>
                      <TableHead className="w-40">操作</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {pagedReports.items.map((r) => (
                      <TableRow key={r.id}>
                        <TableCell>{r.id}</TableCell>
                        <TableCell>{r.reporter}</TableCell>
                        <TableCell>{`${r.target_type} #${r.target_id}`}</TableCell>
                        <TableCell>{r.reason}</TableCell>
                        <TableCell>
                          <Badge
                            variant={r.status === "open" ? "warning"
                              : r.status === "resolved" ? "success" : "secondary"}
                          >
                            {r.status}
                          </Badge>
                        </TableCell>
                        <TableCell>
                          {r.status === "open" && (
                            <div className="flex gap-2">
                              <Button
                                size="sm"
                                onClick={() => act(
                                  () => post(`/api/v1/admin/reports/${r.id}/status`,
                                    { status: "resolved" }, token), "已处理")}
                              >
                                已处理
                              </Button>
                              <Button
                                size="sm"
                                variant="outline"
                                onClick={() => act(
                                  () => post(`/api/v1/admin/reports/${r.id}/status`,
                                    { status: "dismissed" }, token), "已驳回")}
                              >
                                驳回
                              </Button>
                            </div>
                          )}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
                <Pagination page={pagedReports.page} pageCount={pagedReports.pageCount}
                  total={pagedReports.total} onChange={pagedReports.setPage} />
                </>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="matches">
          <Card>
            <CardContent className="pt-5">
              {matches.length === 0 ? (
                <EmptyState title="还没有对局" />
              ) : (
                <>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-14">ID</TableHead>
                      <TableHead className="w-24">游戏</TableHead>
                      <TableHead className="w-28">类型</TableHead>
                      <TableHead>对阵</TableHead>
                      <TableHead className="w-24">状态</TableHead>
                      <TableHead className="w-44">时间</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {pagedMatches.items.map((m) => (
                      <TableRow key={m.id}>
                        <TableCell>{m.id}</TableCell>
                        <TableCell>{m.game}</TableCell>
                        <TableCell>{m.kind}</TableCell>
                        <TableCell>
                          {m.kind === "pvp"
                            ? (m.players || []).map((p) => p.name).join(" vs ")
                            : (m.models || []).map((x) => x.name).join(" vs ")}
                        </TableCell>
                        <TableCell>
                          <Badge
                            variant={m.status === "finished" ? "success"
                              : m.status === "failed" ? "destructive" : "info"}
                          >
                            {m.status}
                          </Badge>
                        </TableCell>
                        <TableCell>
                          {new Date(m.created_at * 1000).toLocaleString("zh-CN", { hour12: false })}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
                <Pagination page={pagedMatches.page} pageCount={pagedMatches.pageCount}
                  total={pagedMatches.total} onChange={pagedMatches.setPage} />
                </>
              )}
            </CardContent>
          </Card>
        </TabsContent>
        <TabsContent value="ugc">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">待审核（pending）</CardTitle>
            </CardHeader>
            <CardContent>
              {ugc.length === 0 ? (
                <EmptyState title="审核队列为空" />
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-14">ID</TableHead>
                      <TableHead>标题</TableHead>
                      <TableHead>作者</TableHead>
                      <TableHead className="w-24">版本</TableHead>
                      <TableHead className="w-40">冒烟</TableHead>
                      <TableHead className="w-24">渲染器</TableHead>
                      <TableHead className="w-56">操作</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {pagedUgc.items.map((g) => (
                      <TableRow key={g.id}>
                        <TableCell>{g.id}</TableCell>
                        <TableCell>{g.title}</TableCell>
                        <TableCell>{g.author}</TableCell>
                        <TableCell>v{g.version}</TableCell>
                        <TableCell>
                          {g.smoke && g.smoke.ok
                            ? <Badge variant="success">通过</Badge>
                            : <Badge variant="destructive">失败</Badge>}
                        </TableCell>
                        <TableCell>
                          {g.meta && g.meta.renderer
                            ? <Button size="sm" variant="outline" onClick={() => openRenderer(g)}>查看</Button>
                            : "—"}
                        </TableCell>
                        <TableCell>
                          <div className="flex gap-2">
                            <Button size="sm" onClick={() => act(
                              () => post("/api/v1/admin/ugc/" + g.id + "/approve", {}, token),
                              "已通过并发布")}>
                              通过
                            </Button>
                            <Button size="sm" variant="outline" onClick={() => {
                              const note = window.prompt("驳回意见（必填）");
                              if (note && note.trim()) act(
                                () => post("/api/v1/admin/ugc/" + g.id + "/reject",
                                  { note: note.trim() }, token), "已驳回");
                            }}>
                              驳回
                            </Button>
                          </div>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>

          <Card className="mt-5">
            <CardHeader>
              <CardTitle className="text-base">全部游戏</CardTitle>
            </CardHeader>
            <CardContent>
              {ugcAll.length === 0 ? (
                <EmptyState title="还没有 UGC 游戏" />
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-14">ID</TableHead>
                      <TableHead>标题</TableHead>
                      <TableHead>作者</TableHead>
                      <TableHead className="w-24">状态</TableHead>
                      <TableHead className="w-56">渲染器</TableHead>
                      <TableHead className="w-28">操作</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {pagedUgcAll.items.map((g) => (
                      <TableRow key={g.id}>
                        <TableCell>{g.id}</TableCell>
                        <TableCell>{g.title}</TableCell>
                        <TableCell>{g.author}</TableCell>
                        <TableCell>
                          <Badge variant={g.status === "published" ? "success" : g.status === "banned" ? "destructive" : "secondary"}>
                            {g.status}
                          </Badge>
                        </TableCell>
                        <TableCell>
                          {g.meta && g.meta.renderer ? (
                            <div className="flex items-center gap-1.5">
                              {g.renderer_enabled
                                ? <Badge variant="success">已开启</Badge>
                                : <Badge variant="secondary">未开启</Badge>}
                              <Button size="sm" variant="outline" onClick={() => openRenderer(g)}>源码</Button>
                              <Button size="sm" variant={g.renderer_enabled ? "outline" : "default"}
                                onClick={() => toggleRenderer(g, !g.renderer_enabled)}>
                                {g.renderer_enabled ? "关闭" : "开启"}
                              </Button>
                            </div>
                          ) : "—"}
                        </TableCell>
                        <TableCell>
                          {g.status === "banned" ? (
                            <Button size="sm" onClick={() => act(
                              () => post("/api/v1/admin/ugc/" + g.id + "/unban", {}, token),
                              "已恢复为草稿")}>
                              恢复
                            </Button>
                          ) : g.status === "published" ? (
                            <Button size="sm" variant="destructive" onClick={() => act(
                              () => post("/api/v1/admin/ugc/" + g.id + "/ban", {}, token),
                              "已下架")}>
                              下架
                            </Button>
                          ) : null}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      <Dialog open={!!rview} onOpenChange={(v) => { if (!v) setRview(null); }}>
        <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>渲染器审核 · {rview?.game?.title}</DialogTitle>
            <DialogDescription>
              沙箱渲染器默认关闭。开启后前端会用 opaque-origin iframe + Worker 运行下面的代码
              （无 DOM/无网络/无凭证，超时自动降级），请人工核对资源与代码内容。
            </DialogDescription>
          </DialogHeader>
          {rview && (
            <div className="flex flex-col gap-4">
              <div>
                <div className="mb-1.5 text-sm font-medium">
                  资源（{assetList(rview.game).length}）
                </div>
                <div className="flex flex-wrap gap-2">
                  {assetList(rview.game).map((a) => (
                    <AssetThumb key={a.file} url={assetUrlOf(rview.game, a.file)}
                      token={token} name={a.file} />
                  ))}
                  {!assetList(rview.game).length && (
                    <span className="text-sm text-muted-foreground">无</span>
                  )}
                </div>
              </div>
              <div>
                <div className="mb-1.5 text-sm font-medium">
                  渲染器源码{rview.renderer ? `（${rview.renderer.size} B）` : ""}
                </div>
                {rview.renderer ? (
                  <pre className="max-h-72 overflow-auto rounded-md border border-border bg-neutral-50 p-3 text-xs leading-relaxed">{rview.renderer.source}</pre>
                ) : (
                  <p className="text-sm text-muted-foreground">该版本没有自定义渲染器。</p>
                )}
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
