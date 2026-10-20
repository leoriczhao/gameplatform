import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { SwordsIcon, Share2Icon, HistoryIcon, TrophyIcon, BotIcon } from "lucide-react";
import { useAuth } from "../AuthContext.jsx";
import { getJson } from "../api.js";
import { useLogin } from "../components/LoginProvider.jsx";
import { Button } from "../components/ui/button.jsx";
import { Badge } from "../components/ui/badge.jsx";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card.jsx";
import { PageHeader } from "../components/ui/page-header.jsx";
import { Alert } from "../components/ui/alert.jsx";
import { EmptyState } from "../components/ui/empty-state.jsx";
import { Spinner } from "../components/ui/spinner.jsx";
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "../components/ui/table.jsx";
import { Pagination, usePaged } from "../components/ui/pagination.jsx";
import GameStrip from "../components/GameStrip.jsx";
import { resultText, STAT_TAG_VARIANT } from "../matches.js";

/* 战绩（14 重构）：原对战中心「我的对局」独立成页，展示 PvP 对局 + 模型挑战记录。 */
export default function Records() {
  const { user, token, authReady } = useAuth();
  const openLogin = useLogin();
  const [games, setGames] = useState([]);
  const [filter, setFilter] = useState("");
  const [matches, setMatches] = useState([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    getJson("/api/games").then((d) => setGames(d.games || [])).catch(() => {});
  }, []);

  const load = useCallback(async () => {
    if (!user || !token) return;
    setLoading(true);
    try {
      const d = await getJson("/api/v1/matches", token);
      setMatches(d.matches || []);
    } catch (e) { toast.error("加载失败：" + e.message); }
    finally { setLoading(false); }
  }, [user, token]);

  useEffect(() => { load(); }, [load]);

  const scoped = filter ? matches.filter((m) => m.game === filter) : matches;
  const paged = usePaged(scoped, 10);
  const gamesWithMatches = games.filter((g) => matches.some((m) => m.game === g.id));

  const shareMatch = async (id) => {
    const url = `${window.location.origin}/watch/match/${id}`;
    try { await navigator.clipboard.writeText(url); toast.success("回放链接已复制"); }
    catch { toast.warning(`手动复制：${url}`); }
  };

  return (
    <div className="page-shell">
      <PageHeader
        icon={HistoryIcon}
        title="战绩"
        description="我的 PvP 对局与模型挑战记录（含回放/分享）"
        actions={(<Button asChild variant="ghost" size="sm"><Link to="/">大厅</Link></Button>)}
      />

      {!user && authReady && (
        <Alert variant="info">
          <div className="font-semibold">需要登录</div>
          <div className="mt-1 text-sm opacity-90">战绩与账号绑定。</div>
          <Button size="sm" className="mt-3" onClick={openLogin}>登录 / 注册</Button>
        </Alert>
      )}

      {user && (
        <Card>
          <CardHeader className="flex-row items-center gap-2">
            <SwordsIcon className="size-4 text-indigo-600" />
            <CardTitle className="text-base">全部记录（{scoped.length}）</CardTitle>
          </CardHeader>
          <CardContent>
            {gamesWithMatches.length > 1 && (
              <div className="mb-4">
                <GameStrip
                  games={[{ id: "", name: "全部" }, ...gamesWithMatches]}
                  value={filter}
                  onChange={setFilter}
                />
              </div>
            )}
            {loading ? <Spinner text="加载中…" /> :
              paged.items.length === 0 ? (
                <EmptyState icon={HistoryIcon} title="还没有对局记录" description="去打一局人 vs 人或发起模型挑战吧" />
              ) : (
                <>
                <Table>
                  <TableHeader><TableRow>
                    <TableHead className="w-14">ID</TableHead>
                    <TableHead className="w-28">类型</TableHead>
                    <TableHead className="w-28">游戏</TableHead>
                    <TableHead>对阵</TableHead>
                    <TableHead className="w-24">状态</TableHead>
                    <TableHead>结果</TableHead>
                    <TableHead className="w-32">操作</TableHead>
                    <TableHead className="w-40">时间</TableHead>
                  </TableRow></TableHeader>
                  <TableBody>
                    {paged.items.map((m) => (
                      <TableRow key={m.id}>
                        <TableCell>{m.id}</TableCell>
                        <TableCell>{m.kind === "pvp" ? <Badge variant="info"><SwordsIcon className="size-3" /> 人 vs 人</Badge> : <Badge><BotIcon className="size-3" /> 模型战</Badge>}</TableCell>
                        <TableCell>{m.game}</TableCell>
                        <TableCell>
                          {m.kind === "pvp"
                            ? (m.players || []).map((p) => p.name).join(" vs ")
                            : `${m.models?.[0]?.name || "模型A"} vs ${m.models?.[1]?.name || "内置 AI"}`}
                        </TableCell>
                        <TableCell><Badge variant={STAT_TAG_VARIANT[m.status] || "secondary"}>{m.status}</Badge></TableCell>
                        <TableCell>{resultText(m)}</TableCell>
                        <TableCell>
                          {m.status === "finished" ? (
                            <div className="flex flex-wrap gap-1.5">
                              <Button asChild size="sm" variant="outline"><Link to={`/watch/match/${m.id}`}>回放</Link></Button>
                              <Button size="sm" variant="ghost" onClick={() => shareMatch(m.id)}><Share2Icon /> 分享</Button>
                            </div>
                          ) : <span className="text-xs text-muted-foreground">—</span>}
                        </TableCell>
                        <TableCell>{new Date(m.created_at * 1000).toLocaleString("zh-CN", { hour12: false })}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
                <Pagination page={paged.page} pageCount={paged.pageCount} total={paged.total} onChange={paged.setPage} />
                </>
              )
            }
          </CardContent>
        </Card>
      )}
    </div>
  );
}