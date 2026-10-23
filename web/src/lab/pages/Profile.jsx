import "./profile.css";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  ArrowRight,
  Bell,
  CalendarDays,
  Gamepad2,
  LogIn,
  Save,
  Sparkles,
  Swords,
  Trophy,
  UsersRound,
} from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../AuthContext.jsx";
import { putJson } from "../../api.js";
import { getJson, useAsync } from "../api.js";
import { useLabAuth } from "../AuthDialog.jsx";
import {
  Button,
  Card,
  EmptyState,
  ErrorNote,
  Field,
  Loading,
  Pill,
  SectionHead,
  Track,
} from "../ui.jsx";

const QUICK_LINKS = [
  { to: "/matches", icon: Swords, title: "战绩墙", desc: "对局记录、回放与 ELO" },
  { to: "/friends", icon: UsersRound, title: "好友", desc: "按用户名添加与查看好友" },
  { to: "/notifications", icon: Bell, title: "通知", desc: "好友、对局与系统通知" },
];

/* ELO 走势 sparkline：纯 SVG 折线，保留旧页面的算法，只换配色 */
function Sparkline({ points, width = 210, height = 46 }) {
  if (!points || points.length < 2) {
    return <span className="pf-spark-empty">ELO 走势：对局数不足</span>;
  }
  const rs = points.map((p) => p.rating);
  const lo = Math.min(...rs);
  const hi = Math.max(...rs);
  const span = hi - lo || 1;
  const step = width / (rs.length - 1);
  const coords = rs.map((rating, index) => {
    const x = index * step;
    const y = height - 4 - ((rating - lo) / span) * (height - 8);
    return [x, y];
  });
  return (
    <svg
      className="pf-spark"
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label={`ELO 走势：${Math.round(lo)} → ${Math.round(hi)}`}
    >
      <polyline
        className="pf-spark__line"
        points={coords.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" ")}
      />
      {coords.map(([x, y], index) => (
        <circle key={index} className="pf-spark__dot" cx={x.toFixed(1)} cy={y.toFixed(1)} r="1.8" />
      ))}
      <text className="pf-spark__axis" x="0" y={height - 1}>
        {lo.toFixed(0)}
      </text>
      <text className="pf-spark__axis" x={width - 22} y={height - 1}>
        {hi.toFixed(0)}
      </text>
    </svg>
  );
}

/* 个人资料页（Lab UI 版）：资料编辑 + XP/等级 + 战绩统计 + ELO 走势 + 快捷入口 */
export default function Profile() {
  const { user, token, authReady, refreshUser } = useAuth();
  const { openAuth } = useLabAuth();
  const profiled = Boolean(user && token);

  const profileQuery = useAsync(
    () => getJson("/api/v1/profile", token).then((d) => d.profile),
    [token],
    { enabled: profiled },
  );
  const statsQuery = useAsync(() => getJson("/api/v1/stats/me", token), [token], {
    enabled: profiled,
  });

  const [savedProfile, setSavedProfile] = useState(null);
  const [nickname, setNickname] = useState("");
  const [avatar, setAvatar] = useState("");
  const [signature, setSignature] = useState("");
  const [errors, setErrors] = useState({});
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    const data = profileQuery.data;
    setSavedProfile(data || null);
    if (data) {
      setNickname(data.nickname || "");
      setAvatar(data.avatar || "");
      setSignature(data.signature || "");
    }
  }, [profileQuery.data]);

  const save = async () => {
    const value = { nickname, avatar, signature };
    const nextErrors = {};
    if (!value.nickname || !value.nickname.trim()) nextErrors.nickname = "请输入昵称";
    else if (value.nickname.length > 24) nextErrors.nickname = "最多 24 字符";
    if (value.avatar && value.avatar.length > 16) nextErrors.avatar = "最多 16 字符";
    if (value.signature && value.signature.length > 120) nextErrors.signature = "最多 120 字符";
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length) return;

    setSaving(true);
    try {
      const d = await putJson(
        "/api/v1/profile",
        {
          nickname: value.nickname ?? undefined,
          avatar: value.avatar || undefined,
          signature: value.signature ?? undefined,
        },
        token,
      );
      profileQuery.setData(d.profile);
      await refreshUser();
      toast.success("资料已保存");
    } catch (e) {
      toast.error(`保存失败：${e.message}`);
    } finally {
      setSaving(false);
    }
  };

  // 首次数据到达时 next 帧才执行同步 effect，这里直接用查询结果兜底，避免闪一帧空白
  const profile = savedProfile || profileQuery.data || null;
  const stats = statsQuery.data;
  const level = profile ? profile.level : stats ? stats.level : null;
  const xp = profile ? profile.xp : stats ? stats.xp : 0;
  const progress = profile ? profile.level_progress : stats ? stats.level_progress : 0;
  const pct = Math.round((progress || 0) * 100);
  const remaining = Math.max(0, Math.round((1 - (progress || 0)) * 100 * (level || 1)));
  const totals = (stats && stats.totals) || null;
  const gameEntries = stats ? Object.entries(stats.games || {}) : [];

  return (
    <>
      <div className="lab-page-head">
        <div className="lab-page-head__copy">
          <div className="lab-kicker">ACCOUNT / PROFILE</div>
          <h1 className="lab-h1">个人资料</h1>
          <p className="lab-subtitle">昵称会显示在对局、排行榜与聊天中；头像用 emoji 表示</p>
        </div>
        <div className="lab-page-head__actions">
          <Link className="lab-btn lab-btn--outline lab-btn--sm" to="/matches">
            <Swords size={13} />
            战绩墙
          </Link>
          <Link className="lab-btn lab-btn--ghost lab-btn--sm" to="/">
            <Gamepad2 size={13} />
            大厅
          </Link>
        </div>
      </div>

      {!authReady ? (
        <Card>
          <Loading label="检查登录态" />
        </Card>
      ) : null}

      {authReady && !user ? (
        <Card>
          <EmptyState
            icon={<LogIn size={16} />}
            title="需要登录"
            desc="个人资料需要账号。登录后可编辑昵称、头像与签名，并查看战绩墙。"
            action={
              <Button variant="primary" size="sm" onClick={() => openAuth("login")}>
                登录 / 注册
              </Button>
            }
          />
        </Card>
      ) : null}

      {user ? (
        profileQuery.loading && !profile ? (
          <Card>
            <Loading label="载入资料" />
          </Card>
        ) : profileQuery.error && !profile ? (
          <Card>
            <ErrorNote error={profileQuery.error} onRetry={profileQuery.reload} />
          </Card>
        ) : profile ? (
          <>
            <div className="pf-grid">
              <Card className="pf-identity">
                <div className="pf-avatar" aria-hidden="true">
                  {profile.avatar || "🙂"}
                </div>
                <h2 className="pf-name">{profile.nickname}</h2>
                <div className="pf-handle">@{profile.username}</div>
                <div className="pf-badges">
                  <Pill tone="violet">LV {level || 1}</Pill>
                  {profile.role === "admin" ? <Pill tone="amber">管理员</Pill> : null}
                </div>
                <p className={`pf-sig${profile.signature ? "" : " is-empty"}`}>
                  {profile.signature || "这个人很懒，还没有签名"}
                </p>

                <div className="pf-level">
                  <div className="pf-level__row">
                    <span className="lab-label">LEVEL / XP</span>
                    <span className="pf-level__xp">{xp} XP</span>
                  </div>
                  <Track value={pct} />
                  <div className="pf-level__hint">
                    距 LV {(level || 1) + 1} 还差 {remaining} XP
                  </div>
                </div>

                <hr className="lab-rule" />
                <div className="lab-meta-row">
                  <span>注册时间</span>
                  <b>{new Date(profile.created_at * 1000).toLocaleDateString("zh-CN")}</b>
                </div>
              </Card>

              <Card className="pf-edit">
                <div className="lab-card__head">
                  <span className="lab-card__title">EDIT PROFILE</span>
                  <span className="lab-mono" style={{ fontSize: 8 }}>
                    PUT /api/v1/profile
                  </span>
                </div>

                <div className="pf-form">
                  <Field label="昵称" hint="1–24 字符">
                    <input
                      className="lab-input"
                      id="pf-nickname"
                      placeholder="1-24 字符"
                      maxLength={24}
                      value={nickname}
                      onChange={(e) => setNickname(e.target.value)}
                    />
                    {errors.nickname ? (
                      <span className="lab-form-error">{errors.nickname}</span>
                    ) : null}
                  </Field>

                  <Field label="头像（emoji）" hint="如 🦊 / 🐍 / ⚔️，≤16 字符">
                    <div className="pf-avatar-field">
                      <span className="pf-avatar-preview" aria-hidden="true">
                        {avatar || "🙂"}
                      </span>
                      <input
                        className="lab-input"
                        id="pf-avatar"
                        placeholder="如 🦊 / 🐍 / ⚔️"
                        maxLength={16}
                        value={avatar}
                        onChange={(e) => setAvatar(e.target.value)}
                      />
                    </div>
                    {errors.avatar ? <span className="lab-form-error">{errors.avatar}</span> : null}
                  </Field>

                  <Field label="个性签名" hint="≤120 字符">
                    <textarea
                      className="lab-input pf-textarea"
                      id="pf-signature"
                      rows={3}
                      placeholder="一句话介绍自己"
                      maxLength={120}
                      value={signature}
                      onChange={(e) => setSignature(e.target.value)}
                    />
                    <span className="pf-count">{signature.length} / 120</span>
                    {errors.signature ? (
                      <span className="lab-form-error">{errors.signature}</span>
                    ) : null}
                  </Field>

                  <Button variant="primary" block disabled={saving} onClick={save}>
                    <Save size={14} />
                    {saving ? "保存中…" : "保存资料"}
                  </Button>
                </div>
              </Card>
            </div>

            <section className="pf-record">
              <SectionHead
                title="战绩墙"
                mono="PVP / ELO"
                action={
                  <Link className="lab-link" to="/matches">
                    查看全部对局
                    <ArrowRight size={12} />
                  </Link>
                }
              />
              <Card>
                {statsQuery.loading && !stats ? (
                  <Loading label="载入战绩" />
                ) : statsQuery.error ? (
                  <ErrorNote error={statsQuery.error} onRetry={statsQuery.reload} />
                ) : !stats ? null : (
                  <>
                    <div className="pf-stats">
                      {[
                        ["总对局", totals.games, "", ""],
                        ["胜场", totals.wins, "is-win", ""],
                        ["负场", totals.losses, "is-loss", ""],
                        ["平局", totals.draws, "", ""],
                        ["胜率", Math.round(totals.win_rate * 100), "", "%"],
                        ["当前连胜", totals.current_streak, "is-amber", ""],
                        ["最高连胜", totals.best_streak, "", ""],
                        ["对局时长", Math.round(totals.play_seconds / 60), "", "分钟"],
                      ].map(([label, value, tone, suffix]) => (
                        <div className="pf-stat" key={label}>
                          <span className="pf-stat__label">{label}</span>
                          <span className={`pf-stat__value${tone ? ` ${tone}` : ""}`}>
                            {value}
                            {suffix ? <small className="pf-stat__suffix">{suffix}</small> : null}
                          </span>
                        </div>
                      ))}
                    </div>

                    {gameEntries.length === 0 ? (
                      <EmptyState
                        icon={<Trophy size={15} />}
                        title="还没有 PvP 战绩"
                        desc="还没有打过人 vs 人对局，可从大厅进入各游戏的对战页。"
                        action={
                          <Link className="lab-btn lab-btn--outline lab-btn--sm" to="/">
                            去大厅
                          </Link>
                        }
                      />
                    ) : (
                      <div className="pf-games">
                        {gameEntries.map(([game, g]) => (
                          <div className="pf-game" key={game}>
                            <div className="pf-game__head">
                              <span className="pf-game__name">{game}</span>
                              <span className="lab-mono" style={{ fontSize: 8 }}>
                                {g.games} 对局
                              </span>
                            </div>
                            <div className="pf-game__body">
                              <div className="pf-game__figs">
                                <div>
                                  <span className="lab-label">胜场</span>
                                  <b>{g.wins}</b>
                                </div>
                                <div>
                                  <span className="lab-label">当前 ELO</span>
                                  <b className="is-amber">{Math.round(g.rating)}</b>
                                </div>
                              </div>
                              <Sparkline points={g.history} />
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </>
                )}
              </Card>
            </section>

            <section className="pf-quick">
              <SectionHead title="快捷入口" mono="QUICK LINKS" />
              <div className="pf-quick__grid">
                {QUICK_LINKS.map((item) => {
                  const Icon = item.icon;
                  return (
                    <Link className="pf-quick__card" to={item.to} key={item.to}>
                      <span className="pf-quick__icon">
                        <Icon size={16} />
                      </span>
                      <span className="pf-quick__copy">
                        <span className="pf-quick__title">{item.title}</span>
                        <span className="pf-quick__desc">{item.desc}</span>
                      </span>
                      <ArrowRight className="pf-quick__arrow" size={14} />
                    </Link>
                  );
                })}
              </div>
            </section>
          </>
        ) : null
      ) : null}
    </>
  );
}
