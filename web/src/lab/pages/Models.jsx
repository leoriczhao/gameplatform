import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import {
  AlertTriangle,
  ArrowRight,
  BarChart3,
  Box,
  Check,
  Gauge,
  Plus,
  RefreshCw,
  Trash2,
  Upload,
} from "lucide-react";
import { useAuth } from "../../AuthContext.jsx";
import { useLabAuth } from "../AuthDialog.jsx";
import { del, post, uploadFile, useGames, useModels } from "../api.js";
import { normalizeGame } from "../games.js";
import {
  Button,
  EmptyState,
  ErrorNote,
  Field,
  Loading,
  Modal,
  Pill,
  Track,
} from "../ui.jsx";
import { gameColor, relativeTime } from "../format.js";

const FILTERS = [
  { key: "all", label: "全部" },
  { key: "pass", label: "契约通过" },
  { key: "draft", label: "待校验" },
];

function contractInfo(model) {
  const raw = model.io_contract;
  if (!raw) return null;
  if (typeof raw === "object") return raw;
  const text = String(raw);
  if (!text.trim().startsWith("{")) return { id: text };
  try {
    return JSON.parse(text);
  } catch (e) {
    return { id: text };
  }
}

function evalOf(model) {
  return (model.meta && model.meta.eval) || null;
}

function UploadDialog({ games, token, onClose, onUploaded }) {
  const [name, setName] = useState("");
  const [game, setGame] = useState(games[0] ? games[0].id : "");
  const [file, setFile] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (event) => {
    event.preventDefault();
    if (!file) {
      setError("请选择 .onnx 模型文件");
      return;
    }
    setError("");
    setBusy(true);
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("game", game);
      form.append("name", name.trim());
      const data = await uploadFile("/api/v1/models", form, token);
      toast.success("模型已托管，契约校验通过");
      onUploaded(data.model);
      onClose();
    } catch (e) {
      setError(e.message || "上传失败");
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <Field label="模型名称" hint="1–40 个字符">
        <input
          className="lab-input"
          value={name}
          onChange={(event) => setName(event.target.value)}
          maxLength={40}
          required
        />
      </Field>
      <Field label="目标环境">
        <select className="lab-select" value={game} onChange={(event) => setGame(event.target.value)}>
          {games.map((item) => (
            <option key={item.id} value={item.id}>
              {item.name}
            </option>
          ))}
        </select>
      </Field>
      <Field label="ONNX 文件" hint="上传即校验输入/输出契约，最大 20MB">
        <input
          className="lab-input"
          type="file"
          accept=".onnx"
          onChange={(event) => setFile(event.target.files && event.target.files[0])}
        />
      </Field>
      {error ? <div className="lab-form-error">{error}</div> : null}
      <div className="lab-modal__actions">
        <Button variant="ghost" type="button" onClick={onClose}>
          取消
        </Button>
        <Button variant="primary" type="submit" disabled={busy}>
          {busy ? "校验并上传…" : "上传托管"}
        </Button>
      </div>
    </form>
  );
}

function ChallengeDialog({ model, games, token, onClose, onCreated }) {
  const game = games.find((item) => item.id === model.game);
  const strategies =
    (game && game.meta && Array.isArray(game.meta.opponents) && game.meta.opponents) || [];
  const [strategy, setStrategy] = useState(strategies[0] || "");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (event) => {
    event.preventDefault();
    if (strategies.length === 0) {
      setError("该环境未声明可挑战的 AI 对手，暂不支持模型挑战");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const opponent = `ai:${strategy}`;
      const data = await post(
        "/api/v1/matches",
        { game: model.game, model_a: model.id, model_b: opponent },
        token,
      );
      toast.success("挑战已创建，正在排队执行");
      onCreated(data.match_id);
      onClose();
    } catch (e) {
      setError(e.message || "创建挑战失败");
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <p className="lab-subtitle" style={{ margin: 0 }}>
        <b style={{ color: "var(--lab-text)" }}>{model.name}</b> 将作为 P0 对阵
        {String(model.game).toUpperCase()} 的内置 AI 策略。对局异步执行，完成后进入「对局与回放」。
      </p>
      <Field label="对手策略">
        {strategies.length > 0 ? (
          <select className="lab-select" value={strategy} onChange={(event) => setStrategy(event.target.value)}>
            {strategies.map((item) => (
              <option key={item} value={item}>
                ai:{item}
              </option>
            ))}
          </select>
        ) : (
          <div className="lab-form-error">
            该环境未声明可挑战的 AI 对手（能力声明限制），暂不能发起模型挑战。
          </div>
        )}
      </Field>
      {error ? <div className="lab-form-error">{error}</div> : null}
      <div className="lab-modal__actions">
        <Button variant="ghost" type="button" onClick={onClose}>
          取消
        </Button>
        <Button variant="primary" type="submit" disabled={busy || strategies.length === 0}>
          {busy ? "创建中…" : "发起挑战"}
        </Button>
      </div>
    </form>
  );
}

export default function Models() {
  const { token, user, authReady } = useAuth();
  const { openAuth } = useLabAuth();
  const navigate = useNavigate();
  const loggedIn = Boolean(user) && user.role !== "guest";
  const gamesQuery = useGames();
  const query = useModels(token, Boolean(authReady && loggedIn));
  const [filter, setFilter] = useState("all");
  const [selectedId, setSelectedId] = useState(null);
  const [evalBusy, setEvalBusy] = useState(false);
  const [evalCache, setEvalCache] = useState({});
  const [uploadOpen, setUploadOpen] = useState(false);
  const [challengeFor, setChallengeFor] = useState(null);

  const games = useMemo(
    () => ((gamesQuery.data && gamesQuery.data.games) || []).map((game, index) => normalizeGame(game, index)),
    [gamesQuery.data],
  );
  const models = (query.data && query.data.models) || [];
  const visible = models.filter((model) => {
    if (filter === "pass") return Boolean(model.io_contract);
    if (filter === "draft") return !model.io_contract;
    return true;
  });
  const selected =
    models.find((model) => model.id === selectedId) || visible[0] || models[0] || null;

  const stats = {
    total: models.length,
    passed: models.filter((model) => model.io_contract).length,
    evaluated: models.filter((model) => evalOf(model) || evalCache[model.id]).length,
    challenges: 0,
  };

  const refresh = () => query.reload();

  const evaluate = async (model) => {
    setEvalBusy(true);
    try {
      const data = await post(`/api/v1/models/${model.id}/eval`, {}, token);
      setEvalCache((cache) => ({ ...cache, [model.id]: data.metrics || {} }));
      toast.success(`评估完成：${(data.metrics && data.metrics.games) || 0} 局`);
      refresh();
    } catch (e) {
      toast.error(e.message || "评估失败");
    } finally {
      setEvalBusy(false);
    }
  };

  const remove = async (model) => {
    if (!window.confirm(`删除模型「${model.name}」？`)) return;
    try {
      await del(`/api/v1/models/${model.id}`, token);
      toast.success("模型已删除");
      setSelectedId(null);
      refresh();
    } catch (e) {
      toast.error(e.message || "删除失败");
    }
  };

  if (!authReady) return <Loading label="连接账号服务" />;

  if (!loggedIn) {
    return (
      <>
        <div className="lab-page-head">
          <div className="lab-page-head__copy">
            <h1 className="lab-h1">模型</h1>
            <p className="lab-subtitle">托管 ONNX 策略 · 契约校验 · 评估与模型对抗</p>
          </div>
        </div>
        <div className="lab-card" style={{ padding: 0, overflow: "hidden" }}>
          <EmptyState
            icon={<Box size={18} />}
            title="登录后开始托管模型"
            desc="把训练好的策略导出为 ONNX，上传时平台会按环境的输入/输出契约强制校验；通过后即可评估、发起模型对抗。"
            action={
              <div className="lab-row" style={{ gap: 10, justifyContent: "center" }}>
                <Button variant="primary" onClick={() => openAuth("login")}>
                  登录
                </Button>
                <Button variant="outline" onClick={() => openAuth("register")}>
                  创建账号
                </Button>
              </div>
            }
          />
        </div>
        <div className="lab-card" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <span className="lab-card__title">TRAINING LOOP</span>
          <div className="lab-row" style={{ gap: 10, flexWrap: "wrap" }}>
            {["环境采样", "本地训练", "export_onnx", "上传托管", "评估与对抗"].map((step, index) => (
              <span className="lab-chip" key={step}>
                {String(index + 1).padStart(2, "0")} {step}
              </span>
            ))}
          </div>
          <span className="lab-subtitle" style={{ fontSize: 11.5 }}>
            完整 SDK 与契约说明见 <a className="lab-link lab-link--lime" href="/api.html">API 文档</a>。
          </span>
        </div>
      </>
    );
  }

  return (
    <>
      <div className="lab-page-head">
        <div className="lab-page-head__copy">
          <h1 className="lab-h1">模型</h1>
          <p className="lab-subtitle">托管 ONNX 策略 · 契约校验 · 评估与模型对抗</p>
        </div>
        <div className="lab-page-head__actions">
          <Button variant="outline" size="sm" onClick={() => runBulkEval()}>
            <Gauge size={13} />
            刷新
          </Button>
          <Button variant="primary" size="sm" onClick={() => setUploadOpen(true)}>
            <Upload size={13} />
            上传 ONNX
          </Button>
        </div>
      </div>

      <div className="mdl-stats">
        <div className="mdl-stat">
          <span className="mdl-stat__label">托管模型</span>
          <span className="mdl-stat__value">{stats.total}</span>
          <span className="mdl-stat__delta">账号：{user.nickname || user.username}</span>
        </div>
        <div className="mdl-stat">
          <span className="mdl-stat__label">契约通过</span>
          <span className="mdl-stat__value">
            {stats.passed} / {stats.total || 0}
          </span>
          <span className={`mdl-stat__delta${stats.passed < stats.total ? " is-warn" : ""}`}>
            {stats.total - stats.passed} 个待校验
          </span>
        </div>
        <div className="mdl-stat">
          <span className="mdl-stat__label">已评估</span>
          <span className="mdl-stat__value">{stats.evaluated}</span>
          <span className="mdl-stat__delta">评估结果写入模型 meta</span>
        </div>
        <div className="mdl-stat">
          <span className="mdl-stat__label">挑战</span>
          <span className="mdl-stat__value">—</span>
          <span className="mdl-stat__delta">模型 vs 内置 AI / 其他模型</span>
        </div>
      </div>

      <div className="mdl-toolbar">
        <div className="env-filters">
          {FILTERS.map((item) => (
            <button
              key={item.key}
              type="button"
              className={`env-filter${filter === item.key ? " is-active" : ""}`}
              onClick={() => setFilter(item.key)}
            >
              {item.label}
            </button>
          ))}
        </div>
        <button type="button" className="lab-link" onClick={refresh}>
          <RefreshCw size={11} />
          刷新列表
        </button>
      </div>

      {query.error ? <ErrorNote error={query.error} onRetry={refresh} /> : null}

      {query.loading && models.length === 0 ? (
        <Loading label="载入模型" />
      ) : models.length === 0 ? (
        <div className="lab-card">
          <EmptyState
            icon={<Box size={16} />}
            title="还没有托管的模型"
            desc="导出 ONNX 后上传，平台按环境契约校验输入/输出；通过后就可以评估并让它参与对抗。"
            action={
              <Button variant="primary" size="sm" onClick={() => setUploadOpen(true)}>
                <Plus size={13} />
                上传第一个模型
              </Button>
            }
          />
        </div>
      ) : (
        <div className="mdl-layout">
          <div className="mdl-table-card lab-scroll-x">
            <div className="mdl-thead">
              <span className="mdl-cell mdl-cell--name">模型</span>
              <span className="mdl-cell mdl-cell--game">游戏</span>
              <span className="mdl-cell mdl-cell--contract">契约</span>
              <span className="mdl-cell mdl-cell--eval">评估胜率</span>
              <span className="mdl-cell mdl-cell--record">评估局数</span>
              <span className="mdl-cell mdl-cell--updated">更新</span>
            </div>
            <div className="mdl-tbody">
              {visible.map((model) => {
                const metrics = evalOf(model) || evalCache[model.id];
                const winRate = metrics && metrics.win_rate != null ? metrics.win_rate : null;
                const isSelected = selected && selected.id === model.id;
                return (
                  <div
                    key={model.id}
                    role="button"
                    tabIndex={0}
                    className={`mdl-trow${isSelected ? " is-selected" : ""}`}
                    onClick={() => setSelectedId(model.id)}
                    onKeyDown={(event) => event.key === "Enter" && setSelectedId(model.id)}
                  >
                    <span className="mdl-cell mdl-cell--name">
                      <b>{model.name}</b>
                      <span>
                        {model.model_type || "onnx"} · {relativeTime(model.created_at)}
                      </span>
                    </span>
                    <span className="mdl-cell mdl-cell--game" style={{ color: gameColor(model.game) }}>
                      {String(model.game).toUpperCase()}
                    </span>
                    <span className="mdl-cell mdl-cell--contract">
                      <Pill tone={model.io_contract ? "green" : "amber"} dot>
                        {model.io_contract ? "PASS" : "DRAFT"}
                      </Pill>
                    </span>
                    <span className="mdl-cell mdl-cell--eval">
                      <span className="mdl-eval-bar">
                        <Track value={winRate != null ? Math.round(winRate * 100) : 0} small />
                      </span>
                      <span className="mdl-eval-val">
                        {winRate != null ? `${Math.round(winRate * 100)}%` : "—"}
                      </span>
                    </span>
                    <span className="mdl-cell mdl-cell--record">{metrics ? metrics.games || "—" : "—"}</span>
                    <span className="mdl-cell mdl-cell--updated">{relativeTime(model.created_at)}</span>
                  </div>
                );
              })}
            </div>
            <div className="mdl-tfoot">
              <span>
                显示 {visible.length} / {models.length} 个模型
              </span>
              <div className="mdl-pager">
                <button type="button" className="is-active">1</button>
              </div>
            </div>
          </div>

          <ModelDetail
            model={selected}
            evaluate={evaluate}
            evalBusy={evalBusy}
            evalCache={evalCache}
            onChallenge={() => setChallengeFor(selected)}
            onDelete={() => remove(selected)}
          />
        </div>
      )}

      {uploadOpen ? (
        <Modal title="上传 ONNX 模型" onClose={() => setUploadOpen(false)}>
          <UploadDialog
            games={games}
            token={token}
            onClose={() => setUploadOpen(false)}
            onUploaded={(model) => {
              setSelectedId(model && model.id);
              refresh();
            }}
          />
        </Modal>
      ) : null}

      {challengeFor ? (
        <Modal title="发起模型挑战" onClose={() => setChallengeFor(null)}>
          <ChallengeDialog
            model={challengeFor}
            games={games}
            token={token}
            onClose={() => setChallengeFor(null)}
            onCreated={(matchId) => navigate(`/matches?match=${matchId}`)}
          />
        </Modal>
      ) : null}
    </>
  );

  function runBulkEval() {
    refresh();
  }
}

function ModelDetail({ model, evaluate, evalBusy, evalCache, onChallenge, onDelete }) {
  if (!model) return null;
  const contract = contractInfo(model);
  const metrics = evalOf(model) || (evalCache && evalCache[model.id]) || null;
  const winRate = metrics && metrics.win_rate != null ? metrics.win_rate : null;
  return (
    <div className="mdl-detail">
      <div className="mdl-detail__head">
        <div style={{ minWidth: 0 }}>
          <div className="mdl-detail__title">{model.name}</div>
          <div className="mdl-detail__sub">
            <span className="lab-chip" style={{ color: gameColor(model.game) }}>
              {String(model.game).toUpperCase()}
            </span>
            <Pill tone="green" dot>
              已托管
            </Pill>
            <span className="lab-mono" style={{ fontSize: 7.5 }}>#{model.id}</span>
          </div>
        </div>
      </div>

      <div className="lab-meta-row">
        <span>模型类型</span>
        <b>{model.model_type || "onnx"}</b>
      </div>
      <div className="lab-meta-row">
        <span>创建时间</span>
        <b>{relativeTime(model.created_at)}</b>
      </div>
      <div className="lab-meta-row">
        <span>契约状态</span>
        <b>{model.io_contract ? "已通过" : "待校验"}</b>
      </div>

      <hr className="lab-rule" />
      <span className="mdl-section-label">CONTRACT</span>
      {model.io_contract ? (
        <>
          <div className="mdl-check">
            <span className="mdl-check__l">
              <Check size={12} /> 输入 / 输出形状
            </span>
            <span className="mdl-check__v">CHECKED</span>
          </div>
          <div className="mdl-check">
            <span className="mdl-check__l">
              <Check size={12} /> 输出解码
            </span>
            <span className="mdl-check__v">CHECKED</span>
          </div>
          <div className="mdl-check">
            <span className="mdl-check__l">
              <Check size={12} /> 确定性（同 seed）
            </span>
            <span className="mdl-check__v">SEEDED</span>
          </div>
          {contract && contract.id ? (
            <div className="lab-meta-row">
              <span>契约协议</span>
              <b>{contract.id}</b>
            </div>
          ) : (
            <div className="envp-schema">
              {typeof contract === "object" ? JSON.stringify(contract, null, 2).slice(0, 220) : String(contract)}
            </div>
          )}
        </>
      ) : (
        <div className="lab-row" style={{ gap: 7, color: "var(--lab-amber)", fontSize: 11 }}>
          <AlertTriangle size={13} />
          该模型尚未通过契约校验，可能无法参与对战
        </div>
      )}

      <hr className="lab-rule" />
      <span className="mdl-section-label">EVALUATION</span>
      {metrics ? (
        <>
          <div className="mdl-eval">
            <div>
              <div className="mdl-eval__big">
                {winRate != null ? `${Math.round(winRate * 100)}%` : "—"}
              </div>
              <div className="mdl-eval__cap">
                {winRate != null ? "对内置基线的胜率" : "无胜率（单人评分环境）"}
              </div>
            </div>
            {metrics.avg_score != null ? (
              <span className="lab-chip">AVG SCORE {metrics.avg_score}</span>
            ) : null}
          </div>
          <div className="lab-meta-row">
            <span>评估局数</span>
            <b>{metrics.games ?? "—"}</b>
          </div>
          {metrics.avg_score != null ? (
            <div className="lab-meta-row">
              <span>平均得分</span>
              <b>{metrics.avg_score}</b>
            </div>
          ) : null}
          {metrics.avg_length != null ? (
            <div className="lab-meta-row">
              <span>平均步数</span>
              <b>{metrics.avg_length}</b>
            </div>
          ) : null}
        </>
      ) : (
        <span className="lab-subtitle" style={{ fontSize: 11 }}>
          还没有评估结果。点击「评估」让模型在服务端跑 N 局。
        </span>
      )}

      <div className="mdl-detail__spacer" />
      <div className="mdl-detail__actions">
        <Button variant="outline" size="sm" onClick={() => evaluate(model)} disabled={evalBusy || !model.io_contract}>
          <BarChart3 size={12} />
          {evalBusy ? "评估中…" : "评估"}
        </Button>
        <Button variant="primary" size="sm" className="lab-grow" onClick={onChallenge} disabled={!model.io_contract}>
          发起模型挑战
          <ArrowRight size={12} />
        </Button>
        <Button variant="danger" size="sm" onClick={onDelete} title="删除模型">
          <Trash2 size={12} />
        </Button>
      </div>
    </div>
  );
}
