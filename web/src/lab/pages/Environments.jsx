import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { BookOpen, Gamepad2, Layers, Upload } from "lucide-react";
import { useGames } from "../api.js";
import { FALLBACK_GAMES, normalizeGame, sortGames } from "../games.js";
import EnvCard from "../EnvCard.jsx";
import { EmptyState, ErrorNote, LinkButton, Loading } from "../ui.jsx";

const FILTERS = [
  { key: "all", label: "全部" },
  { key: "official", label: "官方环境" },
  { key: "ugc", label: "社区游戏包" },
  { key: "pvp", label: "支持 PvP" },
];

function isOfficial(game) {
  return !game.author || game.author === "官方" || game.author === "system";
}

export default function Environments() {
  const query = useGames();
  const [filter, setFilter] = useState("all");
  const games = (query.data && query.data.games) || [];
  const useFallback = !query.loading && games.length === 0;
  const normalized = useMemo(() => {
    const list = sortGames(useFallback ? FALLBACK_GAMES : games).map((game, index) =>
      normalizeGame(game, index),
    );
    return list;
  }, [games, useFallback]);
  const visible = normalized.filter((game) => {
    if (filter === "official") return isOfficial(game);
    if (filter === "ugc") return !isOfficial(game);
    if (filter === "pvp") return game.pvp;
    return true;
  });

  return (
    <>
      <div className="lab-page-head">
        <div className="lab-page-head__copy">
          <h1 className="lab-h1">环境</h1>
          <p className="lab-subtitle">
            官方种子环境与社区游戏包共享同一条沙箱管线与 OpenEnv 契约。
          </p>
        </div>
        <div className="lab-page-head__actions">
          <LinkButton variant="outline" size="sm" href="/api.html" target="_blank" rel="noreferrer">
            <BookOpen size={13} />
            API 文档
          </LinkButton>
          <LinkButton variant="primary" size="sm" href="/ugc">
            <Upload size={13} />
            上传游戏包
          </LinkButton>
        </div>
      </div>

      <div className="env-head">
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
        <span className="lab-mono" style={{ fontSize: 9 }}>
          {visible.length} ENVIRONMENTS · OPENENV 0.4.1
        </span>
      </div>

      {query.loading ? (
        <Loading label="载入环境目录" />
      ) : query.error && useFallback ? (
        <ErrorNote error={query.error} onRetry={query.reload} />
      ) : null}

      {visible.length === 0 ? (
        <div className="lab-card">
          <EmptyState
            icon={<Gamepad2 size={16} />}
            title="这个分类下还没有环境"
            desc="换一个筛选条件，或上传一个自己的游戏包（沙箱隔离、契约校验后进入大厅）。"
            action={
              <Link className="lab-link lab-link--lime" to="/ugc">
                上传游戏包
              </Link>
            }
          />
        </div>
      ) : (
        <div className="env-grid">
          {visible.map((game) => (
            <EnvCard key={game.id} game={game} />
          ))}
        </div>
      )}

      <div className="lab-card" style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <Layers size={15} style={{ color: "var(--lab-text-3)", flex: "none" }} />
        <span className="lab-subtitle lab-grow">
          接入新环境只需要一个游戏包：声明契约、渲染与 PvP 能力，平台自动挂载
          <span className="lab-mono" style={{ marginLeft: 6 }}>/api/openenv/{"{game}"}</span>
        </span>
        <Link className="lab-link" to="/api.html">
          游戏接入指南
        </Link>
      </div>
    </>
  );
}
