import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { UsersIcon, UserPlusIcon, UserIcon, Gamepad2Icon } from "lucide-react";
import { useAuth } from "../AuthContext.jsx";
import { del, getJson, post } from "../api.js";
import { useLogin } from "../components/LoginProvider.jsx";
import { toast } from "sonner";
import { Button } from "../components/ui/button.jsx";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card.jsx";
import { Badge } from "../components/ui/badge.jsx";
import { Input } from "../components/ui/input.jsx";
import { Alert } from "../components/ui/alert.jsx";
import { Confirm } from "../components/ui/confirm.jsx";
import { PageHeader } from "../components/ui/page-header.jsx";
import { EmptyState } from "../components/ui/empty-state.jsx";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "../components/ui/table.jsx";
import { Pagination, usePaged } from "../components/ui/pagination.jsx";

/* 好友页（v1.0-b）：直接按用户名加好友（互加）、删除、对局中标记 */
export default function Friends() {
  const { user, token, authReady } = useAuth();
  const [friends, setFriends] = useState([]);
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const openLogin = useLogin();
  const pagedFriends = usePaged(friends, 15);

  const load = useCallback(async () => {
    try {
      const d = await getJson("/api/v1/friends", token);
      setFriends(d.friends || []);
    } catch (e) { /* keep */ }
  }, [token]);

  useEffect(() => {
    if (!user || !token) return undefined;
    load();
    const t = setInterval(load, 15000);
    return () => clearInterval(t);
  }, [user, token, load]);

  const addFriend = async () => {
    const uname = name.trim();
    if (!uname) { toast.info("请输入对方的用户名"); return; }
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
    try {
      await del(`/api/v1/friends/${id}`, token);
      toast.success("已删除好友");
      load();
    } catch (e) {
      toast.error(`删除失败：${e.message}`);
    }
  };

  return (
    <div className="page-shell">
      <PageHeader
        icon={UsersIcon}
        title="好友"
        description="v1 直接按用户名互加，无需对方同意；对方会收到通知"
        actions={(
          <div className="flex flex-wrap items-center gap-2">
            <Button asChild variant="outline" size="sm">
              <Link to="/profile"><UserIcon /> 资料</Link>
            </Button>
            <Button asChild variant="ghost" size="sm">
              <Link to="/"><Gamepad2Icon /> 大厅</Link>
            </Button>
          </div>
        )}
      />

      {!user && authReady && (
        <Alert variant="info" className="mb-6">
          <div className="font-semibold">需要登录</div>
          <div className="text-sm opacity-90">好友功能需要账号。</div>
          <div className="mt-3 flex gap-2">
            <Button size="sm" onClick={openLogin}>登录 / 注册</Button>
          </div>
        </Alert>
      )}

      {user && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">添加好友（按用户名）</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex w-full max-w-[420px] gap-2">
              <Input
                placeholder="输入对方的用户名，如 deploycheck"
                value={name}
                onChange={(e) => setName(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") addFriend(); }}
              />
              <Button disabled={adding} onClick={addFriend}>
                <UserPlusIcon /> 添加
              </Button>
            </div>

            <div className="mt-4">
              {friends.length === 0 ? (
                <EmptyState
                  icon={UsersIcon}
                  title="还没有好友，加一个吧"
                />
              ) : (
                <>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>好友</TableHead>
                      <TableHead className="w-24">状态</TableHead>
                      <TableHead className="w-24">操作</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {pagedFriends.items.map((f) => (
                      <TableRow key={f.id}>
                        <TableCell>
                          <div className="flex items-center gap-3">
                            <span className="text-[28px] leading-none">{f.avatar || "🙂"}</span>
                            <div>
                              <div className="font-medium">
                                {f.nickname}{" "}
                                <span className="text-xs text-muted-foreground">@{f.username}</span>
                              </div>
                              {f.signature && (
                                <div className="text-xs text-muted-foreground">{f.signature}</div>
                              )}
                            </div>
                          </div>
                        </TableCell>
                        <TableCell>
                          {f.in_game
                            ? <Badge variant="success">对局中</Badge>
                            : <Badge variant="outline">离线</Badge>}
                        </TableCell>
                        <TableCell>
                          <Confirm
                            title={`删除好友 ${f.nickname}？`}
                            confirmText="删除"
                            cancelText="取消"
                            onConfirm={() => removeFriend(f.id)}
                          >
                            <Button variant="destructive" size="sm">删除</Button>
                          </Confirm>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
                <Pagination page={pagedFriends.page} pageCount={pagedFriends.pageCount}
                  total={pagedFriends.total} onChange={pagedFriends.setPage} />
                </>
              )}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
