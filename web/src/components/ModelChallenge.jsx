import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { BotIcon, Share2Icon, TrophyIcon } from "lucide-react";
import { useAuth } from "../AuthContext.jsx";
import { getJson, post } from "../api.js";
import { Button } from "./ui/button.jsx";
import { Badge } from "./ui/badge.jsx";
import { Input } from "./ui/input.jsx";
import { Label } from "./ui/label.jsx";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select.jsx";
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "./ui/table.jsx";
import { EmptyState } from "./ui/empty-state.jsx";
import GameStrip from "./GameStrip.jsx";
import { resultText, STAT_TAG_VARIANT } from "../matches.js";

/* 模型 vs 模型 挑战（14 重构）：对战中心撤销后迁至 模型托管页 + 游戏页（fixedGame）。
   游戏选择用 GameStrip 磁贴条；对手可为内置 AI 策略（meta.opponents）或他人模型 ID。 */
export default function ModelChallenge({ fixedGame = "", compact = false }) {
  const { user, token } = useAuth();
  const [games, setGames] = useState([]);
  const [game, setGame] = useState(fixedGame || "");
  const [models, setModels] = useState([]);
  const [modelA, setModelA] = useState("");
  const [oppType, setOppType] = useState("ai");
  const [opponentInput, setOpponentInput] = useState({ strategy: "", model_b: "" });
  const [records, setRecords] = useState([]);
  const [creating, setCreating] = useState(false);

  const contractGames = games.filter((g) => g.meta?.contract);
  const gameName = games.find((g) => g.id === game)?.name || game;
  const aiOpps = (games.find((g) => g.id === game)?.meta?.opponents || [])
    .map((s) => ({ value: s, label: "内置 AI · " + s }));

  useEffect(() => {
    getJson("/api/games").then((d) => {
      setGames(d.games || []);
      if (!fixedGame) setGame((cur) => cur || (d.games || []).find((g) => g.meta?.contract)?.id || "");
    }).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fixedGame]);

  const loadModels = useCallback(async () => {
    if (!user || !token || !game) return;
    try {
      const d = await getJson("/api/v1/models", token);
      setModels((d.models || []).filter((m) => m.game === game));
    } catch (e) { /* keep */ }
  }, [user, token, game]);

  const loadRecords = useCallback(async () => {
    if (!user || !token) return;
    try {
      const d = await getJson("/api/v1/matches", token);
      const all = d.matches || [];
      setRecords(game ? all.filter((m) => m.game === game && m.kind !== "pvp") : all.filter((m) => m.kind !== "pvp"));
    } catch (e) { /* keep */ }
  }, [user, token, game]);

  useEffect(() => { if (user && token) { loadModels(); loadRecords(); } }, [user, token, loadModels, loadRecords]);
  useEffect(() => { if (user && token) loadRecords(); }, [game, user, token, loadRecords]);

  const createMatch = async (e) => {
    e.preventDefault();
    if (!modelA) { toast.warning("请先选择一个你的模型（上传区可上传）"); return; }
    if (oppType === "ai" && !opponentInput.strategy) { toast.warning("请选择内置 AI 策略"); return; }
    if (oppType === "model" && !opponentInput.model_b) { toast.warning("请输入对手模型 ID"); return; }
    setCreating(true);
    try {
      const opponent = oppType === "ai" ? `ai:${opponentInput.strategy}` : Number(opponentInput.model_b);
      const data = await post("/api/v1/matches",
        { game, model_a: Number(modelA), model_b: opponent }, token);
      toast.success(`挑战已发起（#${data.match_id}），后台运行中…`);
      setModelA("");
      setOpponentInput({ strategy: "", model_b: "" });
      await loadRecords();
    } catch (err) {
      toast.error(`发起失败：${err.message}`);
    } finally {
      setCreating(false);
    }
  };

  const shareMatch = async (id) => {
    const url = `${window.location.origin}/watch/match/${id}`;
    try { await navigator.clipboard.writeText(url); toast.success("回放链接已复制"); }
    catch { toast.warning(`手动复制：${url}`); }
  };

  if (!user || !token) {
    return <EmptyState icon={BotIcon} title="需要登录" description="模型挑战需要账号（登录后可用）" />;
  }

  return (
    <div className="flex flex-col gap-4">
      {!fixedGame && (
        <div className="flex flex-col gap-2">
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <BotIcon className="size-4 text-indigo-600" /><span className="font-medium">选择游戏（仅开放模型契约的游戏）</span>
          </div>
          <GameStrip games={contractGames} value={game} onChange={setGame} />
        </div>
      )}

      <form onSubmit={createMatch} className="flex flex-col gap-4">
        <div className="flex flex-col gap-1.5">
          <Label>我的模型（{gameName || game}）</Label>
          <Select value={modelA} onValueChange={setModelA} disabled={!models.length}>
            <SelectTrigger className="w-full">
              <SelectValue placeholder={models.length ? "选择我的模型" : "该游戏暂无模型，请先上传"} />
            </SelectTrigger>
            <SelectContent>
              {models.map((m) => (<SelectItem key={m.id} value={String(m.id)}>#{m.id} {m.name}</SelectItem>))}
            </SelectContent>
          </Select>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-2 text-sm">
            <label className="flex items-center gap-1.5"><input type="radio" checked={oppType === "ai"} onChange={() => setOppType("ai")} /> 内置 AI</label>
            <label className="flex items-center gap-1.5"><input type="radio" checked={oppType === "model"} onChange={() => setOppType("model")} /> 其他模型（ID）</label>
          </div>
          {oppType === "ai" ? (
            <Select value={opponentInput.strategy} onValueChange={(v) => setOpponentInput((s) => ({ ...s, strategy: v }))}>
              <SelectTrigger className="w-56"><SelectValue placeholder="选择内置 AI 策略" /></SelectTrigger>
              <SelectContent>
                {(aiOpps.length ? aiOpps : [{ value: "", label: "该游戏未声明对手策略" }]).map((o) => (
                  <SelectItem key={o.value || "none"} value={o.value}>{o.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          ) : (
            <Input type="number" min={1} placeholder="对手模型 ID（任意用户）" className="w-44"
              value={opponentInput.model_b} onChange={(e) => setOpponentInput((s) => ({ ...s, model_b: e.target.value }))} />
          )}
          <Button type="submit" disabled={creating}><BotIcon /> {creating ? "发起中…" : "发起挑战（异步运行，最多 1500 tick）"}</Button>
        </div>
      </form>

      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <TrophyIcon className="size-4 text-indigo-600" /><span className="font-medium">挑战记录（{gameName || "全部契约游戏"}）</span>
      </div>
      {records.length === 0 ? (
        <EmptyState icon={BotIcon} title="还没有挑战记录" description="发起一场模型 vs 模型对战试试" />
      ) : (
        <Table>
          <TableHeader><TableRow>
            <TableHead className="w-14">ID</TableHead>
            <TableHead>对阵</TableHead>
            <TableHead className="w-24">状态</TableHead>
            <TableHead>结果</TableHead>
            <TableHead className="w-32">操作</TableHead>
          </TableRow></TableHeader>
          <TableBody>
            {records.slice(0, compact ? 5 : 20).map((m) => (
              <TableRow key={m.id}>
                <TableCell>{m.id}</TableCell>
                <TableCell>{m.models?.[0]?.name || "模型A"} vs {m.models?.[1]?.name || "内置 AI"}</TableCell>
                <TableCell><Badge variant={STAT_TAG_VARIANT[m.status] || "secondary"}>{m.status}</Badge></TableCell>
                <TableCell>{resultText(m)}</TableCell>
                <TableCell>
                  {m.status === "finished" && (
                    <div className="flex flex-wrap gap-1.5">
                      <Button asChild size="sm" variant="outline"><Link to={`/watch/match/${m.id}`}>回放</Link></Button>
                      <Button size="sm" variant="ghost" onClick={() => shareMatch(m.id)}><Share2Icon /> 分享</Button>
                    </div>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      {!compact && records.length > 20 && <p className="text-xs text-muted-foreground">仅显示最近 20 条；全部记录见 <Link to="/records" className="text-indigo-600 hover:underline">战绩</Link>。</p>}
    </div>
  );
}