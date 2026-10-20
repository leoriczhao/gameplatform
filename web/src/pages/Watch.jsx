import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { EyeIcon, SwordsIcon, HomeIcon, UsersIcon } from "lucide-react";
import UgBoard from "../components/UgBoard.jsx";
import { getJson } from "../api.js";
import { gameMeta } from "../games.js";
import { Button } from "../components/ui/button.jsx";
import { Badge } from "../components/ui/badge.jsx";
import { Alert } from "../components/ui/alert.jsx";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card.jsx";
import { Stat } from "../components/ui/stat.jsx";
import { PageHeader } from "../components/ui/page-header.jsx";

/* 观战页（06 §7 U6）：任何公开/匹配对局都可只读围观（13 G4 通用化）。
   2s 轮询会话状态；通用棋盘渲染 + 双方提交指示，无游戏专属字段。 */
const POLL_MS = 2000;
const SIDE_NAME = { p0: "先手", p1: "后手" };
const CAUSE_LABEL = { destroyed: "全歼", time: "时间到", resigned: "认输", timeout: "超时判负" };

export default function Watch() {
  const { game, sessionId } = useParams();
  const [meta, setMeta] = useState(null);
  const [sess, setSess] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    gameMeta(game).then(setMeta).catch(() => {});
  }, [game]);

  const poll = useCallback(async () => {
    try {
      const d = await getJson(`/api/v1/${game}/play/sessions/${sessionId}`);
      setSess(d.session);
      setError(null);
    } catch (e) {
      setError(e.status === 403
        ? "这是私有对局，不可观战"
        : e.status === 404 ? "对局不存在或已过期" : `加载失败：${e.message}`);
    }
  }, [game, sessionId]);

  useEffect(() => {
    poll();
    const t = setInterval(poll, POLL_MS);
    return () => clearInterval(t);
  }, [poll]);

  const over = sess && sess.status === "finished";
  const winnerName = over && sess.winner != null
    ? (sess.players || []).find((p) => p.side === `p${sess.winner}`)?.name || `p${sess.winner}`
    : null;

  return (
    <div className="page-shell">
      <PageHeader
        icon={EyeIcon}
        title={`观战 · ${game}`}
        description="只读视角：双方提交动作后回合推进，公开对局随时可围观"
        actions={(
          <>
            {sess && (
              <Badge variant={sess.mode === "ranked" ? "warning" : "success"}>
                {sess.mode === "ranked" ? "排位" : "练习"}
              </Badge>
            )}
            <Button asChild variant="ghost" size="sm">
              <Link to="/records"><SwordsIcon /> 战绩</Link>
            </Button>
            <Button asChild variant="ghost" size="sm">
              <Link to="/"><HomeIcon /> 大厅</Link>
            </Button>
          </>
        )}
      />

      {error && <Alert variant="warning" className="mb-6"><div>{error}</div></Alert>}

      {!error && sess && (
        <>
          {over && (
            <Alert variant="success" className="mb-4">
              <div>
                <div className="mb-0.5 font-semibold leading-none tracking-tight">
                  {sess.winner == null
                    ? `对局结束：平局（${CAUSE_LABEL[sess.cause] || sess.cause}）`
                    : `对局结束：${winnerName} 获胜（${CAUSE_LABEL[sess.cause] || sess.cause}）`}
                </div>
                <div className="mt-1 text-sm opacity-90">
                  对局已结束。回放可在「战绩」页查看。
                </div>
              </div>
            </Alert>
          )}
          <div className="flex flex-wrap justify-center gap-5">
            <div className="board-shell">
              <UgBoard state={sess.state} meta={meta} />
            </div>
            <div className="flex w-[300px] flex-col gap-3.5">
              <Card>
                <CardHeader className="flex-row items-center gap-2">
                  <UsersIcon className="size-4 text-indigo-600" />
                  <CardTitle className="text-base">对局信息</CardTitle>
                </CardHeader>
                <CardContent className="flex flex-col gap-3">
                  <div className="flex flex-wrap gap-1.5">
                    {(sess.players || []).map((p) => (
                      <Badge key={p.side} variant={p.side === "p0" ? "info" : "destructive"}>
                        {SIDE_NAME[p.side]} {p.name || "…"}
                        {p.submitted ? " · 已提交 ✓" : ""}
                      </Badge>
                    ))}
                  </div>
                  <Stat label="TICK" value={sess.state?.tick ?? 0} />
                  {sess.state?.score != null && <Stat label="得分" value={sess.state.score} />}
                  <p className="text-xs text-muted-foreground">页面每 2 秒自动刷新。</p>
                </CardContent>
              </Card>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
