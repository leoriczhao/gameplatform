import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import {
  UploadIcon, Gamepad2Icon, RefreshCwIcon, Trash2Icon, SendIcon,
  ArrowLeftIcon, PackageIcon,
} from "lucide-react";
import { useAuth } from "../AuthContext.jsx";
import { useLogin } from "../components/LoginProvider.jsx";
import { getJson, post, uploadFile, del } from "../api.js";
import { Button } from "../components/ui/button.jsx";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card.jsx";
import { Badge } from "../components/ui/badge.jsx";
import { Input } from "../components/ui/input.jsx";
import { Label } from "../components/ui/label.jsx";
import { PageHeader } from "../components/ui/page-header.jsx";
import { EmptyState } from "../components/ui/empty-state.jsx";
import { Alert } from "../components/ui/alert.jsx";
import { Confirm } from "../components/ui/confirm.jsx";

const STATUS = {
  draft: { label: "草稿", variant: "secondary" },
  pending: { label: "待审核", variant: "warning" },
  published: { label: "已公开", variant: "success" },
  banned: { label: "已下架", variant: "destructive" },
  paused: { label: "已暂停", variant: "outline" },
};

/* 作者工作台 /ugc（11 P4）：上传游戏包 → 草稿 → 提交审核 → 查看状态；
   支持新版本、作者下架、删除草稿。 */
export default function UgUpload() {
  const { user, token, authReady } = useAuth();
  const openLogin = useLogin();
  const [games, setGames] = useState(null);
  const [file, setFile] = useState(null);
  const [changelog, setChangelog] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    if (!token) return;
    try {
      const d = await getJson("/api/v1/ugc/games", token);
      setGames(d.games || []);
    } catch (e) { toast.error("加载失败：" + e.message); }
  }, [token]);

  useEffect(() => {
    if (user && token) load();
  }, [user, token, load]);

  const upload = async () => {
    if (!file) { toast.warning("先选择一个 .zip 游戏包"); return; }
    if (!file.name.endsWith(".zip")) { toast.warning("请上传 .zip 包"); return; }
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("changelog", changelog.trim());
      await uploadFile("/api/v1/ugc/games", fd, token);
      toast.success("已上传，进入草稿（沙箱冒烟已通过）");
      setFile(null);
      setChangelog("");
      load();
    } catch (e) {
      toast.error("上传失败：" + e.message);
    } finally {
      setBusy(false);
    }
  };

  const act = async (fn, ok) => {
    try { await fn(); toast.success(ok); load(); }
    catch (e) { toast.error("操作失败：" + e.message); }
  };

  if (!user && authReady) {
    return (
      <div className="page-shell">
        <Alert variant="info">
          <div className="font-semibold">登录后即可上传自己的游戏</div>
          <div className="mt-2"><Button size="sm" onClick={openLogin}>登录 / 注册</Button></div>
        </Alert>
      </div>
    );
  }

  return (
    <div className="page-shell">
      <PageHeader
        icon={UploadIcon}
        title="我的游戏（UGC）"
        description="上传 Python zip 游戏包（EnvAdapter + game.yaml）→ 草稿 → 提交审核 → 公开"
        actions={(
          <Button asChild variant="ghost" size="sm"><Link to="/"><ArrowLeftIcon /> 大厅</Link></Button>
        )}
      />

      <Card className="mb-5">
        <CardHeader><CardTitle className="text-base">上传新游戏</CardTitle></CardHeader>
        <CardContent className="flex flex-col gap-3">
          <div className="flex flex-wrap items-end gap-3">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="ugc-file">游戏包（.zip，≤20MB）</Label>
              <Input id="ugc-file" type="file" accept=".zip"
                onChange={(e) => setFile(e.target.files?.[0] || null)} />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="ugc-changelog">更新说明（可选）</Label>
              <Input id="ugc-changelog" placeholder="初始版本"
                value={changelog} maxLength={200}
                onChange={(e) => setChangelog(e.target.value)} />
            </div>
            <Button onClick={upload} disabled={busy || !file}>
              <PackageIcon /> {busy ? "上传中…" : "上传为草稿"}
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">
            包结构：game.yaml（渲染/pvp/ai 声明）+ __init__.py（暴露 get_adapter()）。
            只允许平台 venv 已有库（标准库白名单 + numpy）。参考 <code>gdk-ug/examples/</code>。
          </p>
        </CardContent>
      </Card>

      {games === null ? (
        <EmptyState title="加载中…" />
      ) : games.length === 0 ? (
        <EmptyState icon={UploadIcon} title="还没有游戏，上传一个试试" />
      ) : (
        <div className="grid grid-cols-1 gap-4">
          {games.map((g) => {
            const st = STATUS[g.status] || { label: g.status, variant: "secondary" };
            return (
              <Card key={g.id}>
                <CardHeader className="flex-row items-center gap-3">
                  <CardTitle className="text-base">{g.title}</CardTitle>
                  <Badge variant={st.variant}>{st.label}</Badge>
                  {g.version && <Badge variant="outline">v{g.version}</Badge>}
                  {g.status === "published" && (
                    <Button asChild size="sm" variant="outline" className="ml-auto">
                      <Link to={"/games/ugc/" + g.slug}><Gamepad2Icon /> 去玩</Link>
                    </Button>
                  )}
                </CardHeader>
                <CardContent className="flex flex-col gap-3">
                  <p className="text-sm text-muted-foreground">{g.description}</p>
                  {g.review_note && (
                    <p className="text-sm text-amber-600">审核意见：{g.review_note}</p>
                  )}
                  {g.smoke && typeof g.smoke.ok === "boolean" && (
                    <p className={"text-xs " + (g.smoke.ok ? "text-emerald-600" : "text-red-600")}>
                      {g.smoke.ok ? "✓ 沙箱冒烟通过" : "✗ 沙箱冒烟失败：" + (g.smoke.error || "未知")}
                    </p>
                  )}
                  <div className="flex flex-wrap gap-2">
                    {g.status === "draft" && (
                      <>
                        <Button size="sm" onClick={() => act(
                          () => post("/api/v1/ugc/games/" + g.id + "/submit", {}, token),
                          "已提交审核")}>
                          <SendIcon /> 提交审核
                        </Button>
                        <Confirm title="删除该草稿？" confirmText="删除"
                          onConfirm={() => act(
                            () => del("/api/v1/ugc/games/" + g.id, token), "已删除")}>
                          <Button size="sm" variant="destructive"><Trash2Icon /> 删除</Button>
                        </Confirm>
                      </>
                    )}
                    {g.status === "pending" && (
                      <Badge variant="warning">等待管理员审核</Badge>
                    )}
                    {g.status === "published" && (
                      <Confirm title="下架该游戏？" confirmText="下架"
                        onConfirm={() => act(
                          () => post("/api/v1/ugc/games/" + g.id + "/unpublish", {}, token),
                          "已下架，回到草稿")}>
                        <Button size="sm" variant="destructive">下架</Button>
                      </Confirm>
                    )}
                    {g.status === "draft" && (
                      <Button size="sm" variant="outline" onClick={() => act(
                        () => post("/api/v1/ugc/games/" + g.id + "/test", {}, token),
                        "冒烟完成")}>
                        <RefreshCwIcon /> 重跑冒烟
                      </Button>
                    )}
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
