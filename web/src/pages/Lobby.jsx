import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  Gamepad2Icon, SwordsIcon, BrainCircuitIcon, BookOpenIcon,
  ArrowRightIcon, UploadIcon, FileCodeIcon,
} from "lucide-react";
import { getJson } from "../api.js";
import { GAME_ICONS } from "../components/GameStrip.jsx";
import { useAuth } from "../AuthContext.jsx";
import { useLogin } from "../components/LoginProvider.jsx";
import { Button } from "../components/ui/button.jsx";
import { Badge } from "../components/ui/badge.jsx";
import { Alert } from "../components/ui/alert.jsx";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card.jsx";
import { Spinner } from "../components/ui/spinner.jsx";
import { cn } from "../lib/utils.js";

const LOOP_STEPS = [
  { n: 1, label: "OpenEnv/SDK", href: "/api.html" },
  { n: 2, label: "export_onnx", href: "/api.html#models" },
  { n: 3, label: "模型托管", href: "/models", highlight: true },
  { n: 4, label: "评估/挑战", href: "/models" },
];

function isUgcGame(g) {
  /* 平台统一路由后无专用 UGC 标记；有作者且非空视为社区包 */
  return Boolean(g.author);
}

export default function Lobby() {
  const [games, setGames] = useState(null);
  const [error, setError] = useState(null);
  const [apiOk, setApiOk] = useState(false);
  const [anns, setAnns] = useState([]);
  const [roomCounts, setRoomCounts] = useState({});
  const { user } = useAuth();
  const openLogin = useLogin();

  useEffect(() => {
    (async () => {
      try {
        const data = await getJson("/api/games");
        setGames(data.games);
        setApiOk(true);
      } catch (e) {
        setError(e.message);
      }
    })();
    getJson("/api/v1/announcements")
      .then((d) => setAnns(d.items || []))
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (!games || !games.length) return undefined;
    const pvpGames = games.filter((g) => g.pvp_enabled);
    if (!pvpGames.length) return undefined;
    const load = async () => {
      const entries = await Promise.all(pvpGames.map(async (g) => {
        try {
          const d = await getJson("/api/v1/" + g.id + "/play/rooms");
          return [g.id, (d.rooms || []).length];
        } catch { return [g.id, null]; }
      }));
      const obj = {};
      entries.forEach(([k, v]) => { obj[k] = v; });
      setRoomCounts(obj);
    };
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, [games]);

  return (
    <div className="page-shell">
      {anns.map((a) => (
        <Alert key={a.id} variant="info" className="mb-3 py-2 text-sm">
          <span className="mr-1.5 text-xs font-medium text-sky-700">公告</span>
          {a.body}
        </Alert>
      ))}

      {/* Hero：训练闭环优先；主 CTA → 模型托管 / API；禁止战绩/玩/PvP 作主 CTA */}
      <section className="mb-4 rounded-lg border border-border bg-card p-4 shadow-sm sm:p-5">
        <Badge variant="info" className="mb-2">RL 实验室大厅</Badge>
        <h1 className="text-xl font-bold tracking-tight sm:text-2xl">
          训练闭环：环境 → ONNX → 托管 → 对抗
        </h1>
        <p className="mt-1.5 max-w-2xl text-sm text-muted-foreground">
          OpenEnv/SDK → export_onnx → 托管评估挑战；网页玩/PvP 仅验证支线。
        </p>

        <div className="mt-3 flex flex-wrap items-center gap-1.5 sm:gap-2">
          {LOOP_STEPS.map((s, i) => (
            <div key={s.n} className="flex items-center gap-1.5 sm:gap-2">
              {i > 0 && <ArrowRightIcon className="size-3 shrink-0 text-muted-foreground/60" />}
              <Link
                to={s.href.startsWith("/api") ? "#" : s.href}
                onClick={s.href.startsWith("/api") ? (e) => { e.preventDefault(); window.open(s.href, "_blank"); } : undefined}
                className={cn(
                  "rounded-md border px-2.5 py-1 text-xs font-medium tabular-nums transition-colors",
                  s.highlight
                    ? "border-indigo-500 bg-indigo-50 text-indigo-700"
                    : "border-border bg-background text-muted-foreground hover:border-indigo-300 hover:text-foreground"
                )}
              >
                {s.n} {s.label}
              </Link>
            </div>
          ))}
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-2">
          <Button asChild size="sm">
            <Link to="/models"><BrainCircuitIcon /> 模型托管</Link>
          </Button>
          <Button asChild size="sm">
            <a href="/api.html" target="_blank" rel="noreferrer">
              <BookOpenIcon /> API 文档
            </a>
          </Button>
          <Button asChild size="sm" variant="outline">
            <Link to="/ugc"><UploadIcon /> 上传游戏</Link>
          </Button>
          {!user && (
            <Button size="sm" variant="outline" onClick={openLogin}>登录</Button>
          )}
        </div>
      </section>

      {error && (
        <Alert variant="destructive" className="mb-4">
          无法连接后端:{error}
        </Alert>
      )}

      {!games && !error && <Spinner size="lg" text="加载游戏列表…" />}

      <div className="mb-2 flex items-end justify-between gap-2">
        <h2 className="text-sm font-semibold">可训练环境</h2>
        <span className="text-[11px] text-muted-foreground">契约优先 · 进入/对战次要</span>
      </div>

      <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2 lg:grid-cols-3">
        {(games || []).map((g) => {
          const Icon = GAME_ICONS[g.id] || Gamepad2Icon;
          const ugc = isUgcGame(g);
          const hasContract = Boolean(g.meta?.contract);
          const openenvPath = g.openenv_url || `/api/openenv/${g.id}`;
          const schemaPath = g.schema_url || `/api/openenv/${g.id}/schema`;
          return (
            <Card key={g.id} className="hover-lift flex flex-col">
              <CardHeader className="flex-row items-start justify-between gap-2 space-y-0 p-3 pb-2">
                <div className="flex min-w-0 items-center gap-2">
                  <div className="flex size-8 shrink-0 items-center justify-center rounded-md border border-indigo-100 bg-indigo-50 text-indigo-600">
                    <Icon className="size-4" />
                  </div>
                  <CardTitle className="truncate text-sm">{g.name}</CardTitle>
                </div>
                <Badge variant={ugc ? "secondary" : "info"} className="shrink-0">
                  {ugc ? "UGC" : "官方"}
                </Badge>
              </CardHeader>
              <CardContent className="flex flex-1 flex-col gap-2 p-3 pt-0">
                <div className="space-y-0.5 font-mono text-[11px] leading-snug text-muted-foreground">
                  <div className="truncate">{openenvPath}</div>
                  <div className="truncate">schema · {schemaPath}</div>
                </div>
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
                  {hasContract ? (
                    <span className="font-medium text-indigo-600">模型契约</span>
                  ) : (
                    <span className="text-muted-foreground">无模型契约</span>
                  )}
                  {g.pvp_enabled && (
                    <span className="text-muted-foreground">
                      房 {roomCounts[g.id] == null ? "…" : roomCounts[g.id]}
                    </span>
                  )}
                </div>
                <div className="mt-auto flex flex-wrap gap-1.5 pt-1">
                  <Button asChild size="sm" variant="secondary">
                    <a href={schemaPath} target="_blank" rel="noreferrer">
                      <FileCodeIcon /> Schema
                    </a>
                  </Button>
                  <Button asChild size="sm" variant="outline">
                    <Link to={`/games/${g.id}`}>进入</Link>
                  </Button>
                  {g.pvp_enabled && (
                    <Button asChild size="sm" variant="outline">
                      <Link to={`/games/${g.id}/pvp`}><SwordsIcon /> 对战</Link>
                    </Button>
                  )}
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>

      {apiOk && (
        <p className="mt-4 text-center text-[11px] text-muted-foreground">
          后端在线 · OpenEnv WebSocket 每连接一环境 · 模型对抗在{" "}
          <Link to="/models" className="text-indigo-600 hover:underline">/models</Link>
        </p>
      )}
    </div>
  );
}
