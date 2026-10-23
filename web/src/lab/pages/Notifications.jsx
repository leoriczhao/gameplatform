import "./notifications.css";
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, Bell, CheckCheck, Gamepad2, LogIn } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../AuthContext.jsx";
import { getJson, post } from "../api.js";
import { useLabAuth } from "../AuthDialog.jsx";
import { clock } from "../format.js";
import { Button, Card, EmptyState, ErrorNote, Loading, Pill } from "../ui.jsx";

const POLL_MS = 30000;

function formatTime(seconds) {
  return new Date(seconds * 1000).toLocaleString("zh-CN", { hour12: false });
}

/* 通知中心（Lab UI 版）：全部通知 + 未读标记 + 一键已读；30s 轮询 */
export default function Notifications() {
  const { user, token, authReady } = useAuth();
  const { openAuth } = useLabAuth();
  const [items, setItems] = useState(null);
  const [unread, setUnread] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [marking, setMarking] = useState(false);
  const [lastUpdated, setLastUpdated] = useState(0);

  const load = useCallback(
    async ({ silent = false } = {}) => {
      if (!token) return;
      if (!silent) {
        setLoading(true);
        setError(null);
      }
      try {
        const d = await getJson("/api/v1/notifications", token);
        setItems(d.items || []);
        setUnread(d.unread || 0);
        setLastUpdated(Date.now());
        if (!silent) setError(null);
      } catch (e) {
        // 轮询失败保留旧列表（与旧页面一致），首次加载失败展示错误
        if (!silent) setError(e);
      } finally {
        if (!silent) setLoading(false);
      }
    },
    [token],
  );

  useEffect(() => {
    if (!user || !token) {
      setItems(null);
      setUnread(0);
      return undefined;
    }
    load();
    const timer = setInterval(() => load({ silent: true }), POLL_MS);
    return () => clearInterval(timer);
  }, [user, token, load]);

  const markAll = async () => {
    setMarking(true);
    try {
      await post("/api/v1/notifications/read", {}, token);
      toast.success("已全部标记为已读");
      load({ silent: true });
    } catch (e) {
      toast.error(`操作失败：${e.message}`);
    } finally {
      setMarking(false);
    }
  };

  const list = items || [];

  return (
    <>
      <div className="lab-page-head">
        <div className="lab-page-head__copy">
          <div className="lab-kicker">SOCIAL / NOTIFICATIONS</div>
          <h1 className="lab-h1">通知中心</h1>
          <p className="lab-subtitle">好友、对局与系统通知（落库存储，轮询推送）</p>
        </div>
        <div className="lab-page-head__actions">
          {unread > 0 ? (
            <Button variant="outline" size="sm" disabled={marking} onClick={markAll}>
              <CheckCheck size={13} />
              {marking ? "处理中…" : `全部已读（${unread}）`}
            </Button>
          ) : null}
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
            desc="通知需要账号。登录后可接收好友、对局与系统通知。"
            action={
              <Button variant="primary" size="sm" onClick={() => openAuth("login")}>
                登录 / 注册
              </Button>
            }
          />
        </Card>
      ) : null}

      {user ? (
        <Card flush>
          <div className="nt-head">
            <span className="nt-summary">
              <Bell size={13} />
              <b>{items === null ? "—" : list.length}</b> 条通知
              {unread > 0 ? <span className="nt-unread">· {unread} 条未读</span> : null}
            </span>
            <span className="lab-mono" style={{ fontSize: 8 }}>
              POLL {POLL_MS / 1000}S
            </span>
          </div>

          {loading && items === null ? (
            <Loading label="载入通知" />
          ) : error ? (
            <div className="nt-error">
              <ErrorNote error={error} onRetry={() => load()} />
            </div>
          ) : list.length === 0 ? (
            <EmptyState
              icon={<Bell size={16} />}
              title="暂无通知"
              desc="好友请求、对局结果与系统消息会出现在这里。"
            />
          ) : (
            <div className="nt-list">
              {list.map((n) => (
                <div className={`nt-item${n.read ? "" : " is-unread"}`} key={n.id}>
                  <span className="nt-icon" aria-hidden="true">
                    <Bell size={13} />
                  </span>
                  <div className="nt-body">
                    <div className="nt-top">
                      <span className="nt-text">{n.body}</span>
                      {!n.read ? <Pill tone="lime">未读</Pill> : null}
                    </div>
                    <div className="nt-meta">
                      <span className="nt-time">{formatTime(n.created_at)}</span>
                      {n.link ? (
                        <Link className="nt-link" to={n.link}>
                          查看
                          <ArrowRight size={11} />
                        </Link>
                      ) : null}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}

          {items !== null && !error ? (
            <div className="nt-foot">
              <span>每 {POLL_MS / 1000} 秒自动刷新</span>
              <span>最近更新 {lastUpdated ? clock(lastUpdated / 1000) : "—"}</span>
            </div>
          ) : null}
        </Card>
      ) : null}
    </>
  );
}
