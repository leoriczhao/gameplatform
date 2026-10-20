import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  BrainCircuitIcon, Trash2Icon, UploadIcon, SwordsIcon, FlaskConicalIcon,
} from "lucide-react";
import { useAuth } from "../AuthContext.jsx";
import { getJson, post, del, uploadFile } from "../api.js";
import { useLogin } from "../components/LoginProvider.jsx";
import { toast } from "sonner";
import { Button } from "../components/ui/button.jsx";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card.jsx";
import { Badge } from "../components/ui/badge.jsx";
import { Input } from "../components/ui/input.jsx";
import { Label } from "../components/ui/label.jsx";
import { Alert } from "../components/ui/alert.jsx";
import { Confirm } from "../components/ui/confirm.jsx";
import { PageHeader } from "../components/ui/page-header.jsx";
import { EmptyState } from "../components/ui/empty-state.jsx";
import { Spinner } from "../components/ui/spinner.jsx";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../components/ui/select.jsx";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "../components/ui/table.jsx";
import { cn } from "../lib/utils.js";
import { resultText, STAT_TAG_VARIANT } from "../matches.js";

/* CHANGE-20261014-rl-lab-ux：上传条 + 我的模型表 + 右侧工作台双态（挑战 / 评估）
   无 API 变更；评估结果常驻工作台（非仅 Dialog）。 */

function resolveMetrics(model, evalCache) {
  return evalCache[model?.id] || model?.meta?.metrics || model?.meta?.last_eval || null;
}

function lastEvalCell(model, evalCache) {
  const m = resolveMetrics(model, evalCache);
  if (!m) return { text: "未评估", className: "text-muted-foreground" };
  if (m.error || m.failed) return { text: "失败", className: "text-red-600" };
  if (m.win_rate != null) {
    return { text: `通过 · ${m.win_rate}`, className: "text-emerald-700" };
  }
  if (m.avg_score != null) {
    return { text: `通过 · ${m.avg_score}`, className: "text-emerald-700" };
  }
  return { text: "通过", className: "text-emerald-700" };
}

function ChallengeWorkbench({
  model, games, token, onDone,
}) {
  const gameMeta = games.find((g) => g.id === model.game);
  const aiOpps = (gameMeta?.meta?.opponents || []).map((s) => ({
    value: s, label: s,
  }));
  const [oppType, setOppType] = useState("ai");
  const [strategy, setStrategy] = useState(aiOpps[0]?.value || "");
  const [modelB, setModelB] = useState("");
  const [creating, setCreating] = useState(false);
  const [records, setRecords] = useState([]);

  useEffect(() => {
    setStrategy(aiOpps[0]?.value || "");
    setOppType("ai");
    setModelB("");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [model.id, model.game]);

  const loadRecords = useCallback(async () => {
    if (!token) return;
    try {
      const d = await getJson("/api/v1/matches", token);
      const all = d.matches || [];
      setRecords(all.filter((m) => m.game === model.game && m.kind !== "pvp").slice(0, 8));
    } catch (e) { /* keep */ }
  }, [token, model.game]);

  useEffect(() => { loadRecords(); }, [loadRecords]);

  const createMatch = async () => {
    if (oppType === "ai" && !strategy) { toast.warning("请选择内置 AI 策略"); return; }
    if (oppType === "model" && !modelB) { toast.warning("请输入对手模型 ID"); return; }
    setCreating(true);
    try {
      const opponent = oppType === "ai" ? `ai:${strategy}` : Number(modelB);
      const data = await post("/api/v1/matches",
        { game: model.game, model_a: Number(model.id), model_b: opponent }, token);
      toast.success(`挑战已发起（#${data.match_id}），后台运行中…`);
      onDone?.();
      await loadRecords();
    } catch (err) {
      toast.error(`发起失败：${err.message}`);
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
        {["1 游戏", "2 我的模型", "3 对手", "4 发起"].map((label, i) => (
          <span key={label} className="flex items-center gap-1.5">
            {i > 0 && <span className="text-border">→</span>}
            <span className={cn(
              "rounded px-1.5 py-0.5",
              i === 2 ? "bg-indigo-50 font-medium text-indigo-700" : "bg-neutral-50"
            )}>{label}</span>
          </span>
        ))}
      </div>

      <div className="space-y-2 text-sm">
        <div className="flex items-center gap-2">
          <span className="w-16 shrink-0 text-xs text-muted-foreground">1. 游戏</span>
          <Badge variant="secondary">{model.game}</Badge>
          <span className="text-[11px] text-muted-foreground">来自所选模型</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="w-16 shrink-0 text-xs text-muted-foreground">2. 我的模型</span>
          <span className="font-medium">{model.name}</span>
          <Badge variant="outline">已锁定</Badge>
        </div>
      </div>

      {/* 3 对手：疏开布局 */}
      <div className="space-y-2">
        <div className="text-xs font-medium text-muted-foreground">3. 对手</div>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          <button
            type="button"
            onClick={() => setOppType("ai")}
            className={cn(
              "rounded-md border p-3 text-left text-sm transition-colors",
              oppType === "ai"
                ? "border-indigo-500 bg-indigo-50/60 ring-1 ring-indigo-500/30"
                : "border-border hover:bg-neutral-50"
            )}
          >
            <div className="flex items-center gap-2">
              <span className={cn(
                "flex size-3.5 items-center justify-center rounded-full border",
                oppType === "ai" ? "border-indigo-600 bg-indigo-600" : "border-muted-foreground/40"
              )}>
                {oppType === "ai" && <span className="size-1.5 rounded-full bg-white" />}
              </span>
              <span className="font-medium">内置 AI</span>
            </div>
          </button>
          <button
            type="button"
            onClick={() => setOppType("model")}
            className={cn(
              "rounded-md border p-3 text-left text-sm transition-colors",
              oppType === "model"
                ? "border-indigo-500 bg-indigo-50/60 ring-1 ring-indigo-500/30"
                : "border-border hover:bg-neutral-50"
            )}
          >
            <div className="flex items-center gap-2">
              <span className={cn(
                "flex size-3.5 items-center justify-center rounded-full border",
                oppType === "model" ? "border-indigo-600 bg-indigo-600" : "border-muted-foreground/40"
              )}>
                {oppType === "model" && <span className="size-1.5 rounded-full bg-white" />}
              </span>
              <span className="font-medium">对手模型 ID</span>
            </div>
          </button>
          <div className="flex flex-col gap-1.5 rounded-md border border-border p-3">
            <Label className="text-xs text-muted-foreground">AI 策略</Label>
            <Select
              value={strategy}
              onValueChange={setStrategy}
              disabled={oppType !== "ai"}
            >
              <SelectTrigger className="h-8 w-full">
                <SelectValue placeholder={aiOpps.length ? "选择策略" : "未声明对手策略"} />
              </SelectTrigger>
              <SelectContent>
                {(aiOpps.length ? aiOpps : [{ value: "_none", label: "无" }]).map((o) => (
                  <SelectItem key={o.value} value={o.value} disabled={o.value === "_none"}>
                    {o.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="flex flex-col gap-1.5 rounded-md border border-border p-3">
            <Label className="text-xs text-muted-foreground">对手模型 ID</Label>
            <Input
              type="number"
              min={1}
              placeholder={oppType === "model" ? "输入模型 ID" : "未选"}
              className="h-8"
              disabled={oppType !== "model"}
              value={modelB}
              onChange={(e) => setModelB(e.target.value)}
            />
          </div>
        </div>
      </div>

      <div className="pt-1">
        <Button className="w-full sm:w-auto" disabled={creating} onClick={createMatch}>
          <SwordsIcon /> {creating ? "发起中…" : "发起挑战"}
        </Button>
        <p className="mt-1 text-[11px] text-muted-foreground">步骤 3/4 · 选好对手后发起</p>
      </div>

      <div className="border-t border-border pt-3">
        <div className="mb-2 text-xs font-medium text-muted-foreground">最近挑战</div>
        {records.length === 0 ? (
          <p className="text-xs text-muted-foreground">暂无挑战记录</p>
        ) : (
          <ul className="space-y-1.5">
            {records.map((m) => (
              <li key={m.id} className="flex flex-wrap items-center gap-2 text-xs">
                <span className="font-mono text-muted-foreground">m-{m.id}</span>
                <Badge variant={STAT_TAG_VARIANT[m.status] || "secondary"} className="text-[10px]">
                  {m.status === "finished" ? "完成" : m.status === "running" ? "运行中" : m.status}
                </Badge>
                {m.status === "finished" && (
                  <span className="text-muted-foreground">{resultText(m)}</span>
                )}
                {(m.status === "finished" || m.status === "running") && (
                  <Link to={`/watch/match/${m.id}`} className="text-indigo-600 hover:underline">回放</Link>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function EvalWorkbench({
  model, metrics, evaling, evalStep, onReEval, onSwitchChallenge,
}) {
  const done = !evaling && metrics;
  const step = evaling ? evalStep : (metrics ? 3 : 1);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
        {["1 排队", "2 跑局", "3 指标"].map((label, i) => (
          <span key={label} className="flex items-center gap-1.5">
            {i > 0 && <span className="text-border">→</span>}
            <span className={cn(
              "rounded px-1.5 py-0.5",
              step === i + 1 || (done && i === 2)
                ? "bg-emerald-50 font-medium text-emerald-700"
                : "bg-neutral-50"
            )}>{label}</span>
          </span>
        ))}
      </div>

      {evaling && (
        <Alert variant="info" className="py-2 text-sm">
          {evalStep <= 1 ? "排队中…" : "跑局中…"}（可能需要几秒）
        </Alert>
      )}

      {done && (
        <>
          <Alert variant="success" className="py-2 text-sm">
            评估完成
            {metrics.games != null && ` · episodes=${metrics.games}`}
            {` · ${model.game} 契约通过`}
          </Alert>
          <div className="text-xs font-medium text-muted-foreground">指标</div>
          <div className="grid grid-cols-3 gap-2">
            <div className="rounded-md border border-border bg-neutral-50/80 p-2.5">
              <div className="text-[10px] uppercase tracking-wide text-muted-foreground">win_rate</div>
              <div className="text-lg font-semibold tabular-nums">
                {metrics.win_rate != null ? metrics.win_rate : "—"}
              </div>
              {metrics.win_rate != null && metrics.games != null && (
                <div className="text-[10px] text-muted-foreground">
                  {Math.round(metrics.win_rate * metrics.games)}/{metrics.games}
                </div>
              )}
            </div>
            <div className="rounded-md border border-border bg-neutral-50/80 p-2.5">
              <div className="text-[10px] uppercase tracking-wide text-muted-foreground">avg_reward</div>
              <div className="text-lg font-semibold tabular-nums">
                {metrics.avg_score != null ? metrics.avg_score : "—"}
              </div>
              <div className="text-[10px] text-muted-foreground">mean</div>
            </div>
            <div className="rounded-md border border-border bg-neutral-50/80 p-2.5">
              <div className="text-[10px] uppercase tracking-wide text-muted-foreground">episodes</div>
              <div className="text-lg font-semibold tabular-nums">
                {metrics.games != null ? metrics.games : "—"}
              </div>
              <div className="text-[10px] text-muted-foreground">完成</div>
            </div>
          </div>
          {(metrics.avg_length != null || metrics.scores) && (
            <p className="text-[11px] text-muted-foreground">
              {metrics.avg_length != null && <>avg_len {metrics.avg_length}</>}
              {Array.isArray(metrics.scores) && metrics.scores.length > 0 && (
                <> · max_reward {Math.max(...metrics.scores)}</>
              )}
            </p>
          )}
          <div className="flex flex-wrap gap-2 pt-1">
            <Button size="sm" onClick={onSwitchChallenge}>
              <SwordsIcon /> 用此模型发起挑战
            </Button>
            <Button size="sm" variant="outline" onClick={onReEval} disabled={evaling}>
              重新评估
            </Button>
          </div>
          <p className="text-[11px] text-muted-foreground">
            评估结果常驻工作台，避免只靠 Dialog；完成后可一键切换到挑战
          </p>
        </>
      )}

      {!evaling && !metrics && (
        <EmptyState
          icon={FlaskConicalIcon}
          title="尚未评估"
          description="点击左侧「评估」或下方按钮开始"
          className="py-8"
        />
      )}

      {!evaling && !metrics && (
        <Button size="sm" onClick={onReEval}>开始评估</Button>
      )}
    </div>
  );
}

export default function Models() {
  const { user, token, authReady } = useAuth();
  const openLogin = useLogin();

  const [games, setGames] = useState([]);
  const [models, setModels] = useState([]);
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [file, setFile] = useState(null);
  const [game, setGame] = useState("");
  const [name, setName] = useState("");
  const [filter, setFilter] = useState("all");
  const [selectedId, setSelectedId] = useState(null);
  const [workMode, setWorkMode] = useState("challenge"); // challenge | eval
  const [evalCache, setEvalCache] = useState({});
  const [evaling, setEvaling] = useState(false);
  const [evalStep, setEvalStep] = useState(1);

  const contractGames = useMemo(
    () => (games || []).filter((g) => g.meta?.contract),
    [games]
  );

  const loadModels = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    try {
      const data = await getJson("/api/v1/models", token);
      setModels(data.models || []);
    } catch (e) {
      toast.error(`加载失败：${e.message}`);
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    getJson("/api/games").then((d) => {
      const list = d.games || [];
      setGames(list);
      const first = list.find((g) => g.meta?.contract);
      if (first) setGame((cur) => cur || first.id);
    }).catch(() => {});
  }, []);

  useEffect(() => {
    if (user && token) loadModels();
  }, [user, token, loadModels]);

  const filtered = useMemo(() => {
    if (filter === "all") return models;
    return models.filter((m) => m.game === filter);
  }, [models, filter]);

  const selected = models.find((m) => m.id === selectedId) || null;

  useEffect(() => {
    if (selectedId && !models.some((m) => m.id === selectedId)) {
      setSelectedId(null);
    }
  }, [models, selectedId]);

  const doUpload = async () => {
    if (!file) { toast.info("请选择 .onnx 模型文件"); return; }
    if (!game) { toast.info("请选择游戏"); return; }
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("game", game);
      fd.append("name", name);
      const data = await uploadFile("/api/v1/models", fd, token);
      toast.success(`模型「${data.model.name}」上传成功（#${data.model.id}，契约 ${data.model.io_contract}）`);
      setName("");
      setFile(null);
      loadModels();
    } catch (e) {
      toast.error(`上传失败：${e.message}`);
    } finally {
      setUploading(false);
    }
  };

  const runEval = async (model) => {
    if (!model) return;
    setSelectedId(model.id);
    setWorkMode("eval");
    setEvaling(true);
    setEvalStep(1);
    const t1 = setTimeout(() => setEvalStep(2), 400);
    try {
      const data = await post(`/api/v1/models/${model.id}/eval`, {}, token);
      setEvalCache((c) => ({ ...c, [model.id]: data.metrics }));
      setEvalStep(3);
    } catch (e) {
      toast.error(`评估失败：${e.message}`);
      setEvalCache((c) => ({ ...c, [model.id]: { failed: true, error: e.message } }));
    } finally {
      clearTimeout(t1);
      setEvaling(false);
    }
  };

  const doDelete = async (model) => {
    try {
      await del(`/api/v1/models/${model.id}`, token);
      toast.success(`模型「${model.name}」已删除`);
      if (selectedId === model.id) setSelectedId(null);
      loadModels();
    } catch (e) {
      toast.error(`删除失败：${e.message}`);
    }
  };

  const filterChips = useMemo(() => {
    const ids = [...new Set([
      ...contractGames.map((g) => g.id),
      ...models.map((m) => m.game),
    ])];
    return ids;
  }, [contractGames, models]);

  return (
    <div className="page-shell">
      <PageHeader
        icon={BrainCircuitIcon}
        title="模型托管"
        description="ONNX 上传 → 契约校验 → 评估 → 挑战"
      />

      {!user && authReady && (
        <Alert variant="info" className="mb-4">
          <div className="font-semibold">需要登录</div>
          <div className="text-sm opacity-90">模型托管与账号绑定，请先登录或注册。</div>
          <div className="mt-2">
            <Button size="sm" onClick={openLogin}>登录</Button>
          </div>
        </Alert>
      )}

      {user && (
        <>
          {/* 上传条 */}
          <div className="mb-3 flex flex-wrap items-end gap-2 rounded-lg border border-border bg-neutral-50/80 p-3">
            <div className="flex flex-col gap-1">
              <Label className="text-xs">游戏</Label>
              <Select value={game} onValueChange={setGame}>
                <SelectTrigger className="h-8 w-32">
                  <SelectValue placeholder="选择游戏" />
                </SelectTrigger>
                <SelectContent>
                  {contractGames.map((g) => (
                    <SelectItem key={g.id} value={g.id}>{g.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="flex flex-col gap-1">
              <Label htmlFor="model-name" className="text-xs">名称</Label>
              <Input
                id="model-name"
                placeholder="snake-dqn-v4"
                maxLength={40}
                className="h-8 w-40"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </div>
            <div className="flex flex-col gap-1">
              <Label htmlFor="model-file" className="text-xs">文件</Label>
              <Input
                id="model-file"
                type="file"
                accept=".onnx"
                className="h-8 w-auto max-w-[11rem] cursor-pointer py-1 text-xs"
                onChange={(e) => setFile(e.target.files?.[0] || null)}
              />
            </div>
            <Button size="sm" className="h-8" disabled={uploading} onClick={doUpload}>
              <UploadIcon /> 上传
            </Button>
            <span className="pb-1.5 text-[11px] text-muted-foreground">
              每游戏最多 5 个 · 契约不符会拒
            </span>
          </div>

          <div className="grid grid-cols-1 gap-3 lg:grid-cols-5">
            {/* 左：我的模型 */}
            <Card className="lg:col-span-3">
              <CardHeader className="flex-row items-center justify-between space-y-0 p-3 pb-2">
                <CardTitle className="text-sm">
                  我的模型
                  <span className="ml-1.5 font-normal text-muted-foreground">{models.length} 个</span>
                </CardTitle>
              </CardHeader>
              <CardContent className="p-3 pt-0">
                <div className="mb-2 flex flex-wrap gap-1">
                  <button
                    type="button"
                    onClick={() => setFilter("all")}
                    className={cn(
                      "rounded-md px-2 py-0.5 text-xs",
                      filter === "all" ? "bg-indigo-600 text-white" : "bg-neutral-100 text-muted-foreground hover:bg-neutral-200"
                    )}
                  >全部</button>
                  {filterChips.map((id) => (
                    <button
                      key={id}
                      type="button"
                      onClick={() => setFilter(id)}
                      className={cn(
                        "rounded-md px-2 py-0.5 text-xs font-mono",
                        filter === id ? "bg-indigo-600 text-white" : "bg-neutral-100 text-muted-foreground hover:bg-neutral-200"
                      )}
                    >{id}</button>
                  ))}
                </div>

                {loading ? (
                  <Spinner text="加载中…" />
                ) : filtered.length === 0 ? (
                  <EmptyState
                    icon={BrainCircuitIcon}
                    title="还没有模型"
                    description="上传第一个 .onnx 吧"
                    className="py-8"
                  />
                ) : (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>名称</TableHead>
                        <TableHead className="w-20">游戏</TableHead>
                        <TableHead className="w-16">契约</TableHead>
                        <TableHead className="w-28">最近评估</TableHead>
                        <TableHead className="w-44">操作</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {filtered.map((r) => {
                        const ev = lastEvalCell(r, evalCache);
                        const active = selectedId === r.id;
                        return (
                          <TableRow
                            key={r.id}
                            className={cn(
                              "cursor-pointer",
                              active && "bg-indigo-50/80 hover:bg-indigo-50"
                            )}
                            onClick={() => {
                              setSelectedId(r.id);
                              if (workMode !== "eval" && workMode !== "challenge") {
                                setWorkMode("challenge");
                              }
                            }}
                          >
                            <TableCell className="font-medium">{r.name}</TableCell>
                            <TableCell className="font-mono text-xs">{r.game}</TableCell>
                            <TableCell>
                              <Badge variant="success" className="text-[10px]">通过</Badge>
                            </TableCell>
                            <TableCell className={cn("text-xs", ev.className)}>{ev.text}</TableCell>
                            <TableCell onClick={(e) => e.stopPropagation()}>
                              <div className="flex flex-wrap items-center gap-1">
                                <Button
                                  size="sm"
                                  variant={workMode === "eval" && active ? "default" : "outline"}
                                  className="h-7 px-2 text-xs"
                                  disabled={evaling && selectedId === r.id}
                                  onClick={() => runEval(r)}
                                >
                                  {evaling && selectedId === r.id ? "评估中…" : "评估"}
                                </Button>
                                <Button
                                  size="sm"
                                  variant={workMode === "challenge" && active ? "default" : "outline"}
                                  className="h-7 px-2 text-xs"
                                  onClick={() => {
                                    setSelectedId(r.id);
                                    setWorkMode("challenge");
                                  }}
                                >
                                  挑战
                                </Button>
                                <Confirm
                                  title={`删除模型「${r.name}」？`}
                                  confirmText="删除"
                                  cancelText="取消"
                                  onConfirm={() => doDelete(r)}
                                >
                                  <Button size="sm" variant="ghost" className="h-7 px-2 text-xs text-red-600 hover:text-red-700">
                                    <Trash2Icon className="size-3.5" /> 删除
                                  </Button>
                                </Confirm>
                              </div>
                            </TableCell>
                          </TableRow>
                        );
                      })}
                    </TableBody>
                  </Table>
                )}
                <p className="mt-2 text-[11px] text-muted-foreground">
                  选中行 · 右侧工作台显示评估/挑战（非仅弹窗）
                </p>
              </CardContent>
            </Card>

            {/* 右：工作台 */}
            <Card className="lg:col-span-2">
              <CardHeader className="space-y-2 p-3 pb-2">
                <div className="flex items-center justify-between gap-2">
                  <CardTitle className="text-sm truncate">
                    {workMode === "eval" ? "评估" : "挑战"} 工作台
                    {selected ? ` · ${selected.name}` : ""}
                  </CardTitle>
                </div>
                <div className="flex gap-1">
                  <button
                    type="button"
                    disabled={!selected}
                    onClick={() => setWorkMode("challenge")}
                    className={cn(
                      "rounded-md px-2.5 py-1 text-xs font-medium disabled:opacity-40",
                      workMode === "challenge"
                        ? "bg-indigo-600 text-white"
                        : "bg-neutral-100 text-muted-foreground hover:bg-neutral-200"
                    )}
                  >挑战</button>
                  <button
                    type="button"
                    disabled={!selected}
                    onClick={() => setWorkMode("eval")}
                    className={cn(
                      "rounded-md px-2.5 py-1 text-xs font-medium disabled:opacity-40",
                      workMode === "eval"
                        ? "bg-indigo-600 text-white"
                        : "bg-neutral-100 text-muted-foreground hover:bg-neutral-200"
                    )}
                  >评估</button>
                </div>
              </CardHeader>
              <CardContent className="p-3 pt-0">
                {!selected ? (
                  <EmptyState
                    icon={BrainCircuitIcon}
                    title="选择左侧模型"
                    description="点击行或「评估」「挑战」打开工作台"
                    className="py-10"
                  />
                ) : workMode === "challenge" ? (
                  <ChallengeWorkbench
                    model={selected}
                    games={games}
                    token={token}
                  />
                ) : (
                  <EvalWorkbench
                    model={selected}
                    metrics={resolveMetrics(selected, evalCache)}
                    evaling={evaling && selectedId === selected.id}
                    evalStep={evalStep}
                    onReEval={() => runEval(selected)}
                    onSwitchChallenge={() => setWorkMode("challenge")}
                  />
                )}
              </CardContent>
            </Card>
          </div>
        </>
      )}

      <p className="mt-4 text-center text-[11px] text-muted-foreground">
        模型以 ONNX 托管 · 契约见{" "}
        <a href="/api.html#models" target="_blank" rel="noreferrer" className="text-indigo-600 hover:underline">
          API 文档
        </a>
        {" · "}无 /arena · 无模型广场/赛季
      </p>
    </div>
  );
}
