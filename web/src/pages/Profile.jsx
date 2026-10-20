import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { UserIcon, UsersIcon, Gamepad2Icon } from "lucide-react";
import { useAuth } from "../AuthContext.jsx";
import { getJson, putJson } from "../api.js";
import LevelBadge from "../components/LevelBadge.jsx";
import { useLogin } from "../components/LoginProvider.jsx";
import { toast } from "sonner";
import { Button } from "../components/ui/button.jsx";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card.jsx";
import { Badge } from "../components/ui/badge.jsx";
import { Input } from "../components/ui/input.jsx";
import { Textarea } from "../components/ui/textarea.jsx";
import { Label } from "../components/ui/label.jsx";
import { Stat } from "../components/ui/stat.jsx";
import { Alert } from "../components/ui/alert.jsx";
import { PageHeader } from "../components/ui/page-header.jsx";

/* ELO 走势 sparkline：纯 SVG 折线（无图表库依赖） */
function Sparkline({ points, width = 220, height = 44 }) {
  if (!points || points.length < 2) {
    return <span className="text-xs text-muted-foreground">ELO 走势：对局数不足</span>;
  }
  const rs = points.map((p) => p.rating);
  const lo = Math.min(...rs), hi = Math.max(...rs);
  const span = hi - lo || 1;
  const step = width / (rs.length - 1);
  const pts = rs.map((r, i) => `${(i * step).toFixed(1)},${(height - 4 - ((r - lo) / span) * (height - 8)).toFixed(1)}`);
  return (
    <svg width={width} height={height} style={{ display: "block" }}>
      <polyline points={pts.join(" ")} fill="none" stroke="#8b5cf6" strokeWidth="2" />
      {pts.map((p, i) => {
        const [x, y] = p.split(",").map(Number);
        return <circle key={i} cx={x} cy={y} r="2" fill="#8b5cf6" />;
      })}
      <text x="0" y={height - 1} fontSize="9" fill="#999">{lo.toFixed(0)}</text>
      <text x={width - 30} y={height - 1} fontSize="9" fill="#999">{hi.toFixed(0)}</text>
    </svg>
  );
}

/* 个人资料页（v1.0-b）：昵称/头像(emoji)/签名编辑 */
export default function Profile() {
  const { user, token, authReady, refreshUser } = useAuth();
  const [profile, setProfile] = useState(null);
  const [saving, setSaving] = useState(false);
  const [stats, setStats] = useState(null);
  const [nickname, setNickname] = useState("");
  const [avatar, setAvatar] = useState("");
  const [signature, setSignature] = useState("");
  const [errors, setErrors] = useState({});
  const openLogin = useLogin();

  useEffect(() => {
    if (!user || !token) return;
    getJson("/api/v1/stats/me", token)
      .then((d) => setStats(d))
      .catch(() => {});
    getJson("/api/v1/profile", token)
      .then((d) => {
        setProfile(d.profile);
        setNickname(d.profile.nickname);
        setAvatar(d.profile.avatar || "");
        setSignature(d.profile.signature || "");
      })
      .catch(() => {});
  }, [user, token]);

  const save = async () => {
    const v = { nickname, avatar, signature };
    const errs = {};
    if (!v.nickname || !v.nickname.trim()) errs.nickname = "请输入昵称";
    else if (v.nickname.length > 24) errs.nickname = "最多 24 字符";
    if (v.avatar && v.avatar.length > 16) errs.avatar = "最多 16 字符";
    if (v.signature && v.signature.length > 120) errs.signature = "最多 120 字符";
    setErrors(errs);
    if (Object.keys(errs).length) return;

    setSaving(true);
    try {
      const d = await putJson("/api/v1/profile", {
        nickname: v.nickname ?? undefined,
        avatar: v.avatar || undefined,
        signature: v.signature ?? undefined,
      }, token);
      setProfile(d.profile);
      await refreshUser();
      toast.success("资料已保存");
    } catch (e) {
      toast.error(`保存失败：${e.message}`);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="page-shell">
      <PageHeader
        icon={UserIcon}
        title="个人资料"
        description="昵称会显示在对局、排行榜与聊天中；头像用 emoji 表示"
        actions={(
          <div className="flex flex-wrap items-center gap-2">
            <Button asChild variant="outline" size="sm">
              <Link to="/friends"><UsersIcon /> 好友</Link>
            </Button>
            <Button asChild variant="ghost" size="sm">
              <Link to="/"><Gamepad2Icon /> 大厅</Link>
            </Button>
          </div>
        )}
      />

      {!user && authReady && (
        <Alert variant="info" className="mb-6">
          <div className="font-semibold">需要登录</div>
          <div className="text-sm opacity-90">个人资料需要账号。</div>
          <div className="mt-3 flex gap-2">
            <Button size="sm" onClick={openLogin}>登录 / 注册</Button>
          </div>
        </Alert>
      )}

      {user && profile && (
        <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
          <Card className="hover-lift">
            <CardHeader>
              <CardTitle className="text-base">我的名片</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col items-center gap-3 text-center">
              <span className="text-6xl leading-none">
                {profile.avatar || "🙂"}
              </span>
              <h2 className="text-xl font-bold">{profile.nickname}</h2>
              <Badge variant="info">@{profile.username}</Badge>
              {profile.role === "admin" && <Badge variant="warning">管理员</Badge>}
              <p className="text-sm text-muted-foreground">
                {profile.signature || "这个人很懒，还没有签名"}
              </p>
              <p className="text-xs text-muted-foreground">
                注册于 {new Date(profile.created_at * 1000).toLocaleDateString("zh-CN")}
              </p>
            </CardContent>
          </Card>

          <Card className="hover-lift">
            <CardHeader>
              <CardTitle className="text-base">编辑资料</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-4">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="pf-nickname">昵称</Label>
                <Input
                  id="pf-nickname"
                  placeholder="1-24 字符"
                  value={nickname}
                  onChange={(e) => setNickname(e.target.value)}
                />
                {errors.nickname && <p className="text-sm text-red-600">{errors.nickname}</p>}
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="pf-avatar">头像（emoji）</Label>
                <Input
                  id="pf-avatar"
                  placeholder="如 🦊 / 🐍 / ⚔️"
                  value={avatar}
                  onChange={(e) => setAvatar(e.target.value)}
                />
                {errors.avatar && <p className="text-sm text-red-600">{errors.avatar}</p>}
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="pf-signature">个性签名</Label>
                <Textarea
                  id="pf-signature"
                  rows={3}
                  placeholder="一句话介绍自己"
                  maxLength={120}
                  value={signature}
                  onChange={(e) => setSignature(e.target.value)}
                />
                {errors.signature && <p className="text-sm text-red-600">{errors.signature}</p>}
              </div>
              <Button className="w-full" disabled={saving} onClick={save}>
                {saving ? "保存中…" : "保存资料"}
              </Button>
            </CardContent>
          </Card>
        </div>
      )}

      {user && stats && (
        <Card className="hover-lift mt-5">
          <CardHeader>
            <CardTitle className="text-base">我的战绩墙</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <div className="flex flex-wrap items-center gap-x-8 gap-y-4">
              <LevelBadge />
              <Stat label="总对局" value={stats.totals.games} />
              <Stat label="胜场" value={stats.totals.wins} valueClassName="text-emerald-400" />
              <Stat label="负场" value={stats.totals.losses} valueClassName="text-red-600" />
              <Stat label="平局" value={stats.totals.draws} />
              <Stat label="胜率" value={Math.round(stats.totals.win_rate * 100)} suffix="%" />
              <Stat label="当前连胜" value={stats.totals.current_streak} valueClassName="text-amber-400" />
              <Stat label="历史最高连胜" value={stats.totals.best_streak} />
              <Stat
                label="对局时长"
                value={Math.round(stats.totals.play_seconds / 60)}
                suffix="分钟"
              />
            </div>
            {Object.entries(stats.games).length === 0 && (
              <p className="text-sm text-muted-foreground">
                还没有打过人 vs 人对局，可从大厅进入各游戏的对战页
              </p>
            )}
            {Object.entries(stats.games).map(([game, g]) => (
              <div key={game} className="rounded-lg border border-border bg-white/[0.03] p-4">
                <div className="mb-3 text-sm font-semibold">{game}</div>
                <div className="flex flex-wrap items-center gap-x-8 gap-y-4">
                  <Stat label="对局" value={g.games} valueClassName="text-base" />
                  <Stat label="胜场" value={g.wins} valueClassName="text-base" />
                  <Stat
                    label="当前 ELO"
                    value={Math.round(g.rating)}
                    valueClassName="text-base text-amber-400"
                  />
                  <Sparkline points={g.history} />
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
