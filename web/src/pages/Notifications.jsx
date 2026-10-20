import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { BellIcon, Gamepad2Icon } from "lucide-react";
import { useAuth } from "../AuthContext.jsx";
import { getJson, post } from "../api.js";
import { useLogin } from "../components/LoginProvider.jsx";
import { toast } from "sonner";
import { Button } from "../components/ui/button.jsx";
import { Card, CardContent } from "../components/ui/card.jsx";
import { Badge } from "../components/ui/badge.jsx";
import { Alert } from "../components/ui/alert.jsx";
import { PageHeader } from "../components/ui/page-header.jsx";
import { EmptyState } from "../components/ui/empty-state.jsx";

/* 通知中心（v1.0-e）：全部通知 + 未读标记 + 一键已读 */
export default function Notifications() {
  const { user, token, authReady } = useAuth();
  const [items, setItems] = useState([]);
  const [unread, setUnread] = useState(0);
  const openLogin = useLogin();

  const load = useCallback(async () => {
    try {
      const d = await getJson("/api/v1/notifications", token);
      setItems(d.items || []);
      setUnread(d.unread || 0);
    } catch (e) { /* keep */ }
  }, [token]);

  useEffect(() => {
    if (!user || !token) return;
    load();
  }, [user, token, load]);

  const markAll = async () => {
    try {
      await post("/api/v1/notifications/read", {}, token);
      toast.success("已全部标记为已读");
      load();
    } catch (e) {
      toast.error(`操作失败：${e.message}`);
    }
  };

  return (
    <div className="page-shell">
      <PageHeader
        icon={BellIcon}
        title="通知中心"
        description="好友、对局与系统通知（落库存储，轮询推送）"
        actions={(
          <div className="flex flex-wrap items-center gap-2">
            {unread > 0 && (
              <Button size="sm" variant="outline" onClick={markAll}>
                全部已读（{unread}）
              </Button>
            )}
            <Button asChild variant="ghost" size="sm">
              <Link to="/"><Gamepad2Icon /> 大厅</Link>
            </Button>
          </div>
        )}
      />

      {!user && authReady && (
        <Alert variant="info" className="mb-6">
          <div className="font-semibold">需要登录</div>
          <div className="text-sm opacity-90">通知需要账号。</div>
          <div className="mt-3 flex gap-2">
            <Button size="sm" onClick={openLogin}>登录 / 注册</Button>
          </div>
        </Alert>
      )}

      {user && (
        <Card>
          <CardContent className="pt-5">
            {items.length === 0 ? (
              <EmptyState icon={BellIcon} title="暂无通知" />
            ) : (
              <div className="flex flex-col gap-2">
                {items.map((n) => (
                  <div
                    key={n.id}
                    className={`flex flex-col gap-1 rounded-lg p-3 ${
                      n.read ? "" : "border border-sky-500/20 bg-sky-500/10"
                    }`}
                  >
                    <div className="flex items-center gap-2">
                      <span className="text-sm">{n.body}</span>
                      {!n.read && <Badge variant="info">未读</Badge>}
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="text-xs text-muted-foreground">
                        {new Date(n.created_at * 1000).toLocaleString("zh-CN", { hour12: false })}
                      </span>
                      {n.link && (
                        <Link to={n.link} className="text-xs text-indigo-600 hover:underline">
                          查看 →
                        </Link>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
