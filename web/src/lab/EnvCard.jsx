import { Link } from "react-router-dom";
import { ArrowRight, Play } from "lucide-react";
import { Chip, Pill } from "./ui.jsx";
import MiniBoard from "./MiniBoard.jsx";
import { envChips } from "./games.js";

export default function EnvCard({ game }) {
  const chips = envChips(game);
  return (
    <article className="lab-env-card">
      <div className="lab-env-card__top">
        <span className="lab-env-card__code">{game.code}</span>
        <Pill tone="green" dot>
          READY
        </Pill>
      </div>
      <div>
        <div className="lab-env-card__name">{game.name}</div>
        <div className="lab-env-card__en">
          {game.en}
          {game.version ? ` · v${game.version}` : ""}
          {game.author ? ` · ${game.author}` : ""}
        </div>
      </div>
      <p className="lab-env-card__desc">{game.desc}</p>
      <div className="lab-env-card__preview">
        <MiniBoard game={game.id} />
      </div>
      <div className="lab-env-card__chips">
        {chips.map((chip) => (
          <Chip key={chip}>{chip}</Chip>
        ))}
        {game.hasAi ? <Chip>AI</Chip> : null}
      </div>
      <div className="lab-env-card__foot">
        <Link className="lab-link lab-link--lime" to={`/environments/${game.id}`}>
          打开环境
          <ArrowRight size={12} />
        </Link>
        <div className="lab-row" style={{ gap: 8 }}>
          {game.pvp ? (
            <span className="lab-mono" style={{ color: "var(--lab-green)", letterSpacing: "0.1em" }}>
              PVP
            </span>
          ) : null}
          <a className="lab-icon-btn lab-icon-btn--bare" href={`/games/${game.id}`} title="试玩（旧版页面）">
            <Play size={13} />
          </a>
        </div>
      </div>
    </article>
  );
}
