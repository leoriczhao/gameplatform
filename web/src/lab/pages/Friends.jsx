import "./friends.css";
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  Bell,
  Gamepad2,
  LogIn,
  Trash2,
  UserPlus,
  UserRound,
  UsersRound,
} from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../AuthContext.jsx";
import { del, getJson, post } from "../api.js";
import { useLabAuth } from "../AuthDialog.jsx";
import { Button, Card, EmptyState, ErrorNote, Field, Loading, Modal, Pill } from "../ui.jsx";

const PAGE_SIZE = 15;
const POLL_MS = 15000;

/* 好友页（Lab UI 版）：按用户名直接互加、删除、对局中标记；保留 15s 轮询 */
export default function Friends() {
  const { user, token, authReady } = useAuth();
  const { openAuth } = useLabAuth();
  const [friends, setFriends] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [name, setName] = useState("");
  const [adding, setAdding] = useState(false);
  const [page, setPage] = useState(0);
  const [removeTarget, setRemoveTarget] = useState(null);
  const [removing, setRemoving] = useState(false);

  const load = useCallback(
    async ({ silent = false } = {}) => {
      if (!token) return;
      if (!silent) {
        setLoading(true);
        setError(null);
      }
      try {
        const d = await getJson("/api/v1/friends", token);
        setFriends(d.friends || []);
        if (!silent) setError(null);
      } catch (e) {
        // 轮询失败时保留旧列表（与旧页面一致），首次加载失败则展示错误
        if (!silent) setError(e);
      } finally {
        if (!silent) setLoading(false);
      }
    },
    [token],
  );

  useEffect(() => {
    if (!user || !token) {
      setFriends(null);
      return undefined;
    }
    load();
    const timer = setInterval(() => load({ silent: true }), POLL_MS);
    return () => clearInterval(timer);
  }, [user, token, load]);

  const list = friends || [];
  const pageCount = Math.max(1, Math.ceil(list.length / PAGE_SIZE));

  useEffect(() => {
    setPage((current) => Math.min(current, pageCount - 1));
  }, [pageCount]);

  const pageItems = list.slice(page * PAGE_SIZE, page * PAGE_SIZE + PAGE_SIZE);
  const inGameCount = list.filter((f) => f.in_game).length;

  const addFriend = async () => {
    const uname = name.trim();
    if (!uname) {
      toast.info("请输入对方的用户名");
      return;
    }
    setAdding(true);
    try {
      const d = await post("/api/v1/friends", { username: uname }, token);
      toast.success(`已添加 ${d.friend.nickname}（@${d.friend.username}）为好友`);
      setName("");
      load();
    } catch (e) {
      toast.error(`添加失败：${e.message}`);
    } finally {
      setAdding(false);
    }
  };

  const removeFriend = async (id) => {
    setRemoving(true);
    try {
      await del(`/api/v1/friends/${id}`, token);
      toast.success("已删除好友");
      setRemoveTarget(null);
      load();
    } catch (e) {
      toast.error(`删除失败：${e.message}`);
    } finally {
      setRemoving(false);
    }
  };

  return (
    <>
      <div className="lab-page-head">
        <div className="lab-page-head__copy">
          <div className="lab-kicker">SOCIAL / FRIENDS</div>
          <h1 className="lab-h1">好友</h1>
          <p className="lab-subtitle">
            v1 直接按用户名互加，无需对方同意；对方会收到通知
          </p>
        </div>
        <div className="lab-page-head__actions">
          <Link className="lab-btn lab-btn--outline lab-btn--sm" to="/profile">
            <UserRound size={13} />
            资料
          </Link>
          <Link className="lab-btn lab-btn--ghost lab-btn--sm" to="/notifications">
            <Bell size={13} />
            通知
          </Link>
          <Link className="lab-btn lab-btn--ghost lab-btn--sm" to="/">
            <Gamepad2 size={13} />
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
            title="需要登录"
            desc="好友功能需要账号。登录后可添加好友、查看在线状态并互相发送通知。"
            action={
              <Button variant="primary" size="sm" onClick={() => openAuth("login")}>
                登录 / 注册
              </Button>
            }
          />
        </Card>
      ) : null}

      {user ? (
        <Card>
          <div className="lab-card__head">
            <span className="lab-card__title">ADD FRIEND</span>
            <span className="fr-summary">
              <span>
                好友 <b>{friends === null ? "—" : list.length}</b>
              </span>
              <span>
                对局中 <b>{friends === null ? "—" : inGameCount}</b>
              </span>
            </span>
          </div>

          <div className="fr-add">
            <Field label="对方用户名" hint="直接互加，无需对方同意">
              <input
                className="lab-input"
                placeholder="输入对方的用户名，如 deploycheck"
                value={name}
                onChange={(e) => setName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") addFriend();
                }}
              />
            </Field>
            <Button variant="primary" disabled={adding} onClick={addFriend}>
              <UserPlus size={14} />
              {adding ? "添加中…" : "添加"}
            </Button>
          </div>

          {loading && friends === null ? (
            <Loading label="载入好友" />
          ) : error ? (
            <ErrorNote error={error} onRetry={() => load()} />
          ) : list.length === 0 ? (
            <EmptyState
              icon={<UsersRound size={16} />}
              title="还没有好友，加一个吧"
              desc="输入对方的用户名即可互加好友；对方会收到一条好友通知。"
            />
          ) : (
            <>
              <div className="fr-list">
                <div className="fr-list__head">
                  <span>好友</span>
                  <span className="fr-col-status">状态</span>
                  <span className="fr-col-actions">操作</span>
                </div>
                {pageItems.map((f) => (
                  <div className="fr-row" key={f.id}>
                    <span className="fr-avatar" aria-hidden="true">
                      {f.avatar || "🙂"}
                    </span>
                    <div className="fr-who">
                      <div className="fr-name">
                        <b>{f.nickname}</b>
                        <span>@{f.username}</span>
                      </div>
                      {f.signature ? <div className="fr-sig">{f.signature}</div> : null}
                    </div>
                    <div className="fr-status">
                      {f.in_game ? (
                        <Pill tone="green" dot>
                          对局中
                        </Pill>
                      ) : (
                        <Pill tone="neutral">离线</Pill>
                      )}
                    </div>
                    <div className="fr-actions">
                      <Button
                        variant="danger"
                        size="xs"
                        onClick={() => setRemoveTarget(f)}
                      >
                        <Trash2 size={11} />
                        删除
                      </Button>
                    </div>
                  </div>
                ))}
              </div>

              <div className="fr-pager">
                <span className="lab-mono" style={{ fontSize: 8.5 }}>
                  共 {list.length} 位好友 · {inGameCount} 位对局中 · 每 {POLL_MS / 1000}s 自动刷新
                </span>
                {pageCount > 1 ? (
                  <div className="fr-pager__btns">
                    <Button
                      variant="ghost"
                      size="xs"
                      disabled={page === 0}
                      onClick={() => setPage((p) => Math.max(0, p - 1))}
                    >
                      上一页
                    </Button>
                    <span>
                      {page + 1} / {pageCount}
                    </span>
                    <Button
                      variant="ghost"
                      size="xs"
                      disabled={page >= pageCount - 1}
                      onClick={() => setPage((p) => Math.min(pageCount - 1, p + 1))}
                    >
                      下一页
                    </Button>
                  </div>
                ) : null}
              </div>
            </>
          )}
        </Card>
      ) : null}

      {removeTarget ? (
        <Modal title={`删除好友 ${removeTarget.nickname}？`} onClose={() => setRemoveTarget(null)}>
          <p className="lab-subtitle">
            将删除 @{removeTarget.username}，双方好友关系同时解除。
          </p>
          <div className="lab-modal__actions">
            <Button variant="ghost" onClick={() => setRemoveTarget(null)}>
              取消
            </Button>
            <Button
              variant="danger"
              disabled={removing}
              onClick={() => removeFriend(removeTarget.id)}
            >
              <Trash2 size={13} />
              {removing ? "删除中…" : "删除"}
            </Button>
          </div>
        </Modal>
      ) : null}
    </>
  );
}
