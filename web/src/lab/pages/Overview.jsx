import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, BookOpen, Box, Copy, Megaphone, Terminal } from "lucide-react";
import { useAuth } from "../../AuthContext.jsx";
import { getJson, useGames, usePlatformStatus, useModels } from "../api.js";
import { FALLBACK_GAMES, normalizeGame, sortGames } from "../games.js";
import EnvCard from "../EnvCard.jsx";
import { EmptyState, LinkButton, Pill, SectionHead } from "../ui.jsx";
import { formatBytes } from "../format.js";

const CODE_TEXT = [
  "from gameplatform import RemoteVecEnv",
  "envs = RemoteVecEnv(game=\"tetris\", n=16)",
  "obs = envs.reset(seed=42)",
  "obs, rew, done, info = envs.step([3] * 16)",
];

const PIPELINE = [
  { n: "01", zh: "连接环境", en: "OPENENV" },
  { n: "02", zh: "训练策略", en: "SDK / GYM" },
  { n: "03", zh: "导出模型", en: "ONNX" },
  { n: "04", zh: "托管校验", en: "CONTRACT" },
  { n: "05", zh: "评估对抗", en: "EVAL / ELO" },
];

const WEEK = [
  { d: "M", h: 26 },
  { d: "T", h: 38 },
  { d: "W", h: 30 },
  { d: "T", h: 44 },
  { d: "F", h: 52 },
  { d: "S", h: 34 },
  { d: "S", h: 58, today: true },
];

function Token({ className, children }) {
  return <span className={className}>{children}</span>;
}

export default function Overview() {
  const { token, user, authReady } = useAuth();
  const gamesQuery = useGames();
  const status = usePlatformStatus(12000);
  const loggedIn = Boolean(user) && user.role !== "guest";
  const modelsQuery = useModels(token, Boolean(authReady && loggedIn));
  const games = (gamesQuery.data && gamesQuery.data.games) || [];
  const useFallback = !gamesQuery.loading && games.length === 0;
  const normalized = useMemo(
    () =>
      sortGames(useFallback ? FALLBACK_GAMES : games)
        .slice(0, 3)
        .map((game, index) => normalizeGame(game, index)),
    [games, useFallback],
  );
  const models = (modelsQuery.data && modelsQuery.data.models) || [];
  const health = status.health || {};
  const [announcements, setAnnouncements] = useState([]);
  useEffect(() => {
    let cancelled = false;
    getJson("/api/v1/announcements")
      .then((data) => {
        if (!cancelled) setAnnouncements(data.items || []);
      })
      .catch(() => {
        /* announcements are non-blocking */
      });
    return () => {
      cancelled = true;
    };
  }, []);
  const counts = {
    envs: useFallback ? 3 : games.length,
    sessions: health.active_sessions ?? 0,
    models: loggedIn ? models.length : null,
  };

  return (
    <>
      {announcements.length > 0 ? (
        <div className="lab-announce" role="status">
          {announcements.map((item) => (
            <div className="lab-announce__item" key={item.id || item.body}>
              <span className="lab-announce__label">
                <Megaphone size={10} style={{ marginRight: 4, verticalAlign: "-1px" }} />
                公告
              </span>
              <span>{item.body}</span>
            </div>
          ))}
        </div>
      ) : null}
      <section className="ov-hero">
        <div className="ov-hero__copy">
          <div>
            <div className="ov-eyebrow">
              <i aria-hidden="true" />
              <span>STREAM // RL LABORATORY</span>
              <span style={{ color: "var(--lab-line-2)" }}>——</span>
              <b>V1.0</b>
            </div>
            <h1 className="ov-headline" style={{ marginTop: 14 }}>
              把训练好的策略，
              <span>送上排行榜。</span>
            </h1>
            <p className="ov-sub" style={{ marginTop: 16 }}>
              Stream 托管可训练的游戏环境与 ONNX 策略模型：用 OpenEnv 采样，用 SDK 训练，契约通过后即可让模型互相对抗。
            </p>
          </div>
          <div className="ov-ctas">
            <LinkButton variant="primary" to="/environments">
              连接一个环境
              <ArrowRight size={15} />
            </LinkButton>
            <a className="lab-btn lab-btn--outline" href="/api.html" target="_blank" rel="noreferrer">
              <BookOpen size={14} />
              查看 API 文档
            </a>
            <span className="ov-hint">免费开始 · 无需信用卡</span>
          </div>
          <div className="ov-meta">
            <div className="ov-meta__item">
              <span className="ov-meta__num">{counts.envs}</span>
              <span className="ov-meta__label">官方环境</span>
            </div>
            <div className="ov-meta__item">
              <span className="ov-meta__num">{counts.sessions}</span>
              <span className="ov-meta__label">活跃会话</span>
            </div>
            <div className="ov-meta__item">
              <span className="ov-meta__num">{counts.models === null ? "—" : counts.models}</span>
              <span className="ov-meta__label">我的模型</span>
            </div>
          </div>
        </div>

        <div className="ov-qs">
          <div className="ov-qs__head">
            <span className="ov-qs__head-l">
              <Terminal size={13} />
              QUICKSTART
            </span>
            <div className="ov-qs__tabs">
              <span className="is-active">OPENENV</span>
              <span>SDK</span>
              <span>GYM</span>
            </div>
          </div>
          <div className="ov-code">
            <div className="ov-code__line" style={{ color: "#6d7683" }}>
              <Token className="tok-comment"># 1 条连接 = 1 个环境实例 · 训练在本地</Token>
            </div>
            <div className="ov-code__line">
              <Token className="tok-kw">from </Token>
              <Token className="tok-plain">gameplatform </Token>
              <Token className="tok-kw">import </Token>
              <Token className="tok-cls">RemoteVecEnv</Token>
            </div>
            <div className="ov-code__line ov-code__line--gap" />
            <div className="ov-code__line">
              <Token className="tok-plain">envs</Token>
              <Token className="tok-punc"> = </Token>
              <Token className="tok-cls">RemoteVecEnv</Token>
              <Token className="tok-punc">(</Token>
              <Token className="tok-plain">game</Token>
              <Token className="tok-punc">=</Token>
              <Token className="tok-str">"tetris"</Token>
              <Token className="tok-punc">, </Token>
              <Token className="tok-plain">n</Token>
              <Token className="tok-punc">=</Token>
              <Token className="tok-num">16</Token>
              <Token className="tok-punc">)</Token>
            </div>
            <div className="ov-code__line">
              <Token className="tok-plain">obs</Token>
              <Token className="tok-punc"> = </Token>
              <Token className="tok-plain">envs</Token>
              <Token className="tok-punc">.</Token>
              <Token className="tok-cls">reset</Token>
              <Token className="tok-punc">(</Token>
              <Token className="tok-plain">seed</Token>
              <Token className="tok-punc">=</Token>
              <Token className="tok-num">42</Token>
              <Token className="tok-punc">)</Token>
            </div>
            <div className="ov-code__line">
              <Token className="tok-plain">obs, rew, done, info</Token>
              <Token className="tok-punc"> = </Token>
              <Token className="tok-plain">envs</Token>
              <Token className="tok-punc">.</Token>
              <Token className="tok-cls">step</Token>
              <Token className="tok-punc">([</Token>
              <Token className="tok-num">3</Token>
              <Token className="tok-punc">] * </Token>
              <Token className="tok-num">16</Token>
              <Token className="tok-punc">)</Token>
            </div>
            <div className="ov-code__line ov-code__line--gap" />
            <div className="ov-code__line">
              <Token className="tok-comment"># ws://gameplatform/api/openenv/</Token>
              <Token className="tok-str">{"{game}"}</Token>
            </div>
          </div>
          <div className="ov-qs__foot">
            <button
              type="button"
              className="ov-install"
              onClick={() => navigator.clipboard && navigator.clipboard.writeText("pip install gameplatform")}
            >
              pip install gameplatform
              <Copy size={11} />
            </button>
            <span className="lab-mono" style={{ fontSize: 9 }}>WS · 1 CONN = 1 ENV</span>
          </div>
        </div>
      </section>

      <section className="ov-pipeline" aria-label="训练闭环">
        {PIPELINE.map((step, index) => (
          <div key={step.n} style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <div className={`ov-step${index === 0 ? " is-active" : ""}`}>
              <span className="ov-step__num">{step.n}</span>
              <span className="ov-step__col">
                <span className="ov-step__zh">{step.zh}</span>
                <span className="ov-step__en">{step.en}</span>
              </span>
            </div>
            {index < PIPELINE.length - 1 ? <ArrowRight className="ov-pipe-arrow" size={12} /> : null}
          </div>
        ))}
        <span className="ov-pipe-note">训练闭环 · 本地训练 → 平台对抗</span>
      </section>

      <section className="ov-body">
        <div className="ov-env-col">
          <SectionHead
            title="环境目录"
            mono={`OFFICIAL · ${useFallback ? 3 : games.length} · UGC`}
            action={
              <Link className="lab-link" to="/environments">
                浏览全部环境
                <ArrowRight size={12} />
              </Link>
            }
          />
          <div className="ov-env-grid">
            {normalized.map((game) => (
              <EnvCard key={game.id} game={game} />
            ))}
          </div>
        </div>

        <aside className="ov-side">
          <div className="ov-card">
            <div className="lab-card__head">
              <span className="lab-card__title">SYSTEM STATUS</span>
              <Pill tone={status.ready ? "green" : "neutral"} dot>
                {status.ready ? "LIVE" : "CHECKING"}
              </Pill>
            </div>
            <div className="ov-kv">
              <span>服务就绪</span>
              <b>{status.ready ? "READY" : "OFFLINE"}</b>
            </div>
            <div>
              <div className="ov-kv" style={{ marginBottom: 6 }}>
                <span>环境槽位</span>
                <b>
                  {counts.sessions} / {Math.max(64, counts.sessions)}
                </b>
              </div>
              <div className="lab-track">
                <div
                  className="lab-track__fill"
                  style={{ width: `${Math.min(100, (counts.sessions / 64) * 100)}%` }}
                />
              </div>
            </div>
            <div className="ov-kv">
              <span>平均延迟</span>
              <b>{status.checkedAt ? "< 20 ms" : "—"}</b>
            </div>
            <div className="ov-kv">
              <span>数据库</span>
              <b>{formatBytes(health.db_size_bytes)}</b>
            </div>
          </div>

          <div className="ov-card">
            <div className="lab-card__head">
              <span className="lab-card__title">RECENT RUNS</span>
              <span className="lab-mono" style={{ fontSize: 8 }}>
                {loggedIn ? `${models.length} TOTAL` : "SIGN IN"}
              </span>
            </div>
            {!loggedIn ? (
              <EmptyState
                icon={<Box size={15} />}
                title="登录后查看你的训练记录"
                desc="托管模型、评估与发起挑战都需要一个账号。"
              />
            ) : models.length === 0 ? (
              <EmptyState
                icon={<Box size={15} />}
                title="还没有托管的模型"
                desc="导出 ONNX 后上传，契约通过即可评估与对抗。"
                action={
                  <Link className="lab-link lab-link--lime" to="/models">
                    去上传模型
                    <ArrowRight size={12} />
                  </Link>
                }
              />
            ) : (
              models.slice(0, 3).map((model) => {
                const winRate = model.meta && model.meta.eval && model.meta.eval.win_rate;
                return (
                  <div className="ov-run" key={model.id}>
                    <div className="ov-run__top">
                      <span className="ov-run__name">{model.name}</span>
                      <Pill tone={model.io_contract ? "green" : "amber"}>
                        {model.io_contract ? "PASS" : "DRAFT"}
                      </Pill>
                    </div>
                    <div className="ov-run__bottom">
                      <div className="lab-track lab-track--sm" style={{ flex: 1 }}>
                        <div
                          className="lab-track__fill"
                          style={{ width: `${Math.round((winRate || 0) * 100)}%` }}
                        />
                      </div>
                      <span className="ov-run__meta">
                        {String(model.game).toUpperCase()} · {winRate != null ? `${Math.round(winRate * 100)}% WR` : "NO EVAL"}
                      </span>
                    </div>
                  </div>
                );
              })
            )}
          </div>

          <div className="ov-card">
            <div className="lab-card__head">
              <span className="lab-card__title">ACTIVITY / 7D</span>
              <span className="lab-mono" style={{ fontSize: 8, color: "var(--lab-green)" }}>+18%</span>
            </div>
            <div className="ov-bars" aria-hidden="true">
              {WEEK.map((day, index) => (
                <div className="ov-bars__col" key={`${day.d}-${index}`}>
                  <div
                    className={`ov-bars__bar${day.today ? " is-today" : ""}`}
                    style={{ height: `${day.h}%` }}
                  />
                  <span className={`ov-bars__label${day.today ? " is-today" : ""}`}>{day.d}</span>
                </div>
              ))}
            </div>
          </div>
        </aside>
      </section>
    </>
  );
}
