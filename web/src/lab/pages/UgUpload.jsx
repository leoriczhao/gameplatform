import "./ugc-upload.css";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  ArrowLeft,
  CircleAlert,
  FileArchive,
  Gamepad2,
  LogIn,
  Package,
  RefreshCw,
  Send,
  Trash2,
} from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../AuthContext.jsx";
import { del, getJson, post, uploadFile } from "../api.js";
import { useLabAuth } from "../AuthDialog.jsx";
import { formatBytes } from "../format.js";
import {
  Button,
  Card,
  Chip,
  EmptyState,
  ErrorNote,
  Loading,
  Modal,
  Pill,
  SectionHead,
} from "../ui.jsx";

const STATUS = {
  draft: { label: "草稿", tone: "neutral" },
  pending: { label: "待审核", tone: "amber" },
  published: { label: "已公开", tone: "green" },
  banned: { label: "已下架", tone: "red" },
  paused: { label: "已暂停", tone: "neutral" },
};

/* 作者工作台 /ugc（Lab UI 版）：上传游戏包 → 草稿 → 提交审核 → 查看状态；
   支持新版本、作者下架、删除草稿。API 与旧页保持一致。 */
export default function UgUpload() {
  const { user, token, authReady } = useAuth();
  const { openAuth } = useLabAuth();
  const fileInputRef = useRef(null);

  const [games, setGames] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [file, setFile] = useState(null);
  const [changelog, setChangelog] = useState("");
  const [busy, setBusy] = useState(false);
  const [acting, setActing] = useState("");
  const [confirm, setConfirm] = useState(null);
  const [confirmBusy, setConfirmBusy] = useState(false);

  const load = useCallback(
    async ({ silent = false } = {}) => {
      if (!token) return;
      if (!silent) {
        setLoading(true);
        setError(null);
      }
      try {
        const d = await getJson("/api/v1/ugc/games", token);
        setGames(d.games || []);
        if (!silent) setError(null);
      } catch (e) {
        setError(e);
        toast.error("加载失败：" + e.message);
      } finally {
        if (!silent) setLoading(false);
      }
    },
    [token],
  );

  useEffect(() => {
    if (user && token) load();
    if (!user || !token) setGames(null);
  }, [user, token, load]);

  const upload = async () => {
    if (!file) {
      toast.warning("先选择一个 .zip 游戏包");
      return;
    }
    if (!file.name.endsWith(".zip")) {
      toast.warning("请上传 .zip 包");
      return;
    }
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("changelog", changelog.trim());
      await uploadFile("/api/v1/ugc/games", fd, token);
      toast.success("已上传，进入草稿（沙箱冒烟已通过）");
      setFile(null);
      setChangelog("");
      if (fileInputRef.current) fileInputRef.current.value = "";
      load({ silent: true });
    } catch (e) {
      toast.error("上传失败：" + e.message);
    } finally {
      setBusy(false);
    }
  };

  const act = async (fn, ok, key = "") => {
    if (key) setActing(key);
    try {
      await fn();
      toast.success(ok);
      load({ silent: true });
      return true;
    } catch (e) {
      toast.error("操作失败：" + e.message);
      return false;
    } finally {
      if (key) setActing("");
    }
  };

  const runConfirm = async () => {
    if (!confirm) return;
    setConfirmBusy(true);
    try {
      const ok = await confirm.run();
      if (ok) setConfirm(null);
    } finally {
      setConfirmBusy(false);
    }
  };

  const askDelete = (game) =>
    setConfirm({
      title: "删除该草稿？",
      desc: `将删除「${game.title}」的草稿与沙箱冒烟结果。`,
      confirmText: "删除",
      run: () =>
        act(() => del(`/api/v1/ugc/games/${game.id}`, token), "已删除", `${game.id}:delete`),
    });

  const askUnpublish = (game) =>
    setConfirm({
      title: "下架该游戏？",
      desc: `「${game.title}」将回到草稿状态，不再出现在公开目录。`,
      confirmText: "下架",
      run: () =>
        act(
          () => post(`/api/v1/ugc/games/${game.id}/unpublish`, {}, token),
          "已下架，回到草稿",
          `${game.id}:unpublish`,
        ),
    });

  const list = games || [];
  const publishedCount = list.filter((g) => g.status === "published").length;

  return (
    <>
      <div className="lab-page-head">
        <div className="lab-page-head__copy">
          <div className="lab-kicker">CREATOR / UGC</div>
          <h1 className="lab-h1">我的游戏（UGC）</h1>
          <p className="lab-subtitle">
            上传 Python zip 游戏包（EnvAdapter + game.yaml）→ 草稿 → 提交审核 → 公开
          </p>
        </div>
        <div className="lab-page-head__actions">
          <Link className="lab-btn lab-btn--ghost lab-btn--sm" to="/">
            <ArrowLeft size={13} />
            大厅
          </Link>
        </div>
      </div>

      {!authReady ? (
        <Card>
          <Loading label="检查登录态" />
        </Card>
      ) : null}

      {authReady && !user ? (
        <Card>
          <EmptyState
            icon={<LogIn size={16} />}
            title="登录后即可上传自己的游戏"
            desc="作者工作台需要账号。登录后可上传游戏包、提交审核并管理已发布的游戏。"
            action={
              <Button variant="primary" size="sm" onClick={() => openAuth("login")}>
                登录 / 注册
              </Button>
            }
          />
        </Card>
      ) : null}

      {user ? (
        <>
          <Card className="ugu-upload">
            <div className="lab-card__head">
              <span className="lab-card__title">UPLOAD NEW GAME</span>
              <span className="lab-mono" style={{ fontSize: 8 }}>
                POST /api/v1/ugc/games
              </span>
            </div>

            <div className="ugu-form">
              <div className="lab-field">
                <span>游戏包（.zip，≤20MB）</span>
                <label className={`ugu-file${file ? " has-file" : ""}`}>
                  <input
                    ref={fileInputRef}
                    className="ugu-file__input"
                    type="file"
                    accept=".zip"
                    onChange={(e) => setFile(e.target.files?.[0] || null)}
                  />
                  <FileArchive size={14} />
                  <span className="ugu-file__name">
                    {file ? file.name : "选择 .zip 游戏包"}
                  </span>
                  {file ? <span className="ugu-file__size">{formatBytes(file.size)}</span> : null}
                  <span className="ugu-file__btn">选择文件</span>
                </label>
              </div>

              <div className="lab-field">
                <span>更新说明（可选）</span>
                <input
                  className="lab-input"
                  placeholder="初始版本"
                  value={changelog}
                  maxLength={200}
                  onChange={(e) => setChangelog(e.target.value)}
                />
              </div>

              <Button
                variant="primary"
                className="ugu-submit"
                onClick={upload}
                disabled={busy || !file}
              >
                <Package size={14} />
                {busy ? "上传中…" : "上传为草稿"}
              </Button>
            </div>

            <p className="ugu-hint">
              包结构：<code>game.yaml</code>（渲染/pvp/ai 声明）+ <code>__init__.py</code>
              （暴露 get_adapter()）。只允许平台 venv 已有库（标准库白名单 + numpy）。参考{" "}
              <code>gdk-ug/examples/</code>。
            </p>
          </Card>

          <section className="ugu-games-wrap">
            <SectionHead
              title="我的游戏"
              mono={`MY UGC · ${list.length} · ${publishedCount} PUBLISHED`}
            />

            {loading && games === null ? (
              <Card>
                <Loading label="载入游戏列表" />
              </Card>
            ) : error ? (
              <Card>
                <ErrorNote error={error} onRetry={() => load()} />
              </Card>
            ) : list.length === 0 ? (
              <Card>
                <EmptyState
                  icon={<Package size={16} />}
                  title="还没有游戏，上传一个试试"
                  desc="上传 .zip 游戏包后会先进入草稿，沙箱冒烟通过后即可提交审核。"
                />
              </Card>
            ) : (
              <div className="ugu-games">
                {list.map((g) => {
                  const st = STATUS[g.status] || { label: g.status, tone: "neutral" };
                  const submitKey = `${g.id}:submit`;
                  const testKey = `${g.id}:test`;
                  return (
                    <Card className="ugu-game" key={g.id}>
                      <div className="ugu-game__head">
                        <span className="ugu-game__title">{g.title}</span>
                        <Pill tone={st.tone}>{st.label}</Pill>
                        {g.version ? <Chip>v{g.version}</Chip> : null}
                        <span className="ugu-game__spacer" />
                        {g.status === "published" ? (
                          <Link className="lab-btn lab-btn--outline lab-btn--sm" to={"/games/ugc/" + g.slug}>
                            <Gamepad2 size={13} />
                            去玩
                          </Link>
                        ) : null}
                      </div>

                      {g.description ? <p className="ugu-game__desc">{g.description}</p> : null}

                      {g.review_note ? (
                        <div className="ugu-note">
                          <CircleAlert size={13} />
                          <span>审核意见：{g.review_note}</span>
                        </div>
                      ) : null}

                      {g.smoke && typeof g.smoke.ok === "boolean" ? (
                        <div className={`ugu-smoke ${g.smoke.ok ? "is-ok" : "is-fail"}`}>
                          {g.smoke.ok ? (
                            <span>✓ 沙箱冒烟通过</span>
                          ) : (
                            <>
                              <CircleAlert size={12} />
                              <span>✗ 沙箱冒烟失败：{g.smoke.error || "未知"}</span>
                            </>
                          )}
                        </div>
                      ) : null}

                      <div className="ugu-actions">
                        {g.status === "draft" ? (
                          <>
                            <Button
                              variant="primary"
                              size="sm"
                              disabled={acting === submitKey}
                              onClick={() =>
                                act(
                                  () =>
                                    post("/api/v1/ugc/games/" + g.id + "/submit", {}, token),
                                  "已提交审核",
                                  submitKey,
                                )
                              }
                            >
                              <Send size={12} />
                              {acting === submitKey ? "提交中…" : "提交审核"}
                            </Button>
                            <Button
                              variant="outline"
                              size="sm"
                              disabled={acting === testKey}
                              onClick={() =>
                                act(
                                  () => post("/api/v1/ugc/games/" + g.id + "/test", {}, token),
                                  "冒烟完成",
                                  testKey,
                                )
                              }
                            >
                              <RefreshCw size={12} />
                              {acting === testKey ? "冒烟中…" : "重跑冒烟"}
                            </Button>
                            <Button variant="danger" size="sm" onClick={() => askDelete(g)}>
                              <Trash2 size={12} />
                              删除
                            </Button>
                          </>
                        ) : null}

                        {g.status === "pending" ? (
                          <Pill tone="amber">等待管理员审核</Pill>
                        ) : null}

                        {g.status === "published" ? (
                          <Button variant="danger" size="sm" onClick={() => askUnpublish(g)}>
                            下架
                          </Button>
                        ) : null}

                        <span className="ugu-meta">
                          ID #{g.id}
                          {g.slug ? ` · ${g.slug}` : ""}
                        </span>
                      </div>
                    </Card>
                  );
                })}
              </div>
            )}
          </section>
        </>
      ) : null}

      {confirm ? (
        <Modal title={confirm.title} onClose={() => (confirmBusy ? null : setConfirm(null))}>
          <p className="lab-subtitle">{confirm.desc}</p>
          <div className="lab-modal__actions">
            <Button variant="ghost" disabled={confirmBusy} onClick={() => setConfirm(null)}>
              取消
            </Button>
            <Button variant="danger" disabled={confirmBusy} onClick={runConfirm}>
              {confirmBusy ? "处理中…" : confirm.confirmText}
            </Button>
          </div>
        </Modal>
      ) : null}
    </>
  );
}
