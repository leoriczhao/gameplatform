import { useEffect, useState } from "react";
import { BrowserRouter, Routes, Route, Link } from "react-router-dom";
import { Toaster } from "sonner";
import { Gamepad2Icon } from "lucide-react";
import { useAuth } from "./AuthContext.jsx";
import { getJson } from "./api.js";
import { LoginProvider } from "./components/LoginProvider.jsx";
import AppShell from "./components/AppShell.jsx";
import { Alert, AlertDescription } from "./components/ui/alert.jsx";
import { Badge } from "./components/ui/badge.jsx";
import { Button } from "./components/ui/button.jsx";
import Lobby from "./pages/Lobby.jsx";
import Records from "./pages/Records.jsx";
import Models from "./pages/Models.jsx";
import Watch from "./pages/Watch.jsx";
import WatchReplay from "./pages/WatchReplay.jsx";
import Profile from "./pages/Profile.jsx";
import Friends from "./pages/Friends.jsx";
import Admin from "./pages/Admin.jsx";
import Notifications from "./pages/Notifications.jsx";
import UgPlay from "./pages/UgPlay.jsx";
import UgPvp from "./pages/UgPvp.jsx";
import UgUpload from "./pages/UgUpload.jsx";

/* 断线重连横幅（06 §7 U5）：登录后每 5s 轮询 /api/v1/play/active,
   有未完成的 PvP 对局就在顶部提示「回到对局」。 */
function ReconnectBanner() {
  const { user, token } = useAuth();
  const [sessions, setSessions] = useState([]);

  useEffect(() => {
    if (!user || !token) {
      setSessions([]);
      return undefined;
    }
    const load = async () => {
      try {
        const d = await getJson("/api/v1/play/active", token);
        setSessions((d.sessions || []).filter((s) => s.kind === "pvp"));
      } catch (e) { /* keep the old list */ }
    };
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, [user, token]);

  if (!sessions.length) return null;
  return (
    <div className="sticky top-12 z-40 px-3 pt-2 sm:px-5">
      <Alert variant="warning" className="mx-auto max-w-6xl shadow-lg">
        <Gamepad2Icon className="mt-0.5 size-4 shrink-0" />
        <AlertDescription className="flex flex-wrap items-center gap-2">
          <span>你有进行中的对局,可以随时回到棋盘</span>
          {sessions.map((s) => (
            <span key={s.id} className="flex items-center gap-2">
              <Badge variant={s.status === "waiting" ? "warning" : "success"}>
                {s.status === "waiting" ? "等待对手加入" : "对局中"} · 第 {s.tick} 回合
              </Badge>
              <Link to={`/games/${s.game}/pvp?session=${s.id}`}>
                <Button size="sm">回到对局</Button>
              </Link>
            </span>
          ))}
          <button
            type="button"
            onClick={() => setSessions([])}
            className="ml-auto cursor-pointer text-sm text-amber-600/80 hover:text-amber-200"
          >
            关闭
          </button>
        </AlertDescription>
      </Alert>
    </div>
  );
}

/* 14 重构：/arena 破坏性移除；未知路径统一兜底（无跳转、无别名） */
function NotFound() {
  return (
    <div className="page-shell">
      <Alert variant="destructive" className="mx-auto max-w-md">
        <AlertDescription className="flex flex-col items-center gap-3 py-2 text-center">
          <span className="text-base font-semibold">页面不存在（404）</span>
          <span className="text-sm opacity-90">该链接已失效或已移除（如旧的对战中心入口）。</span>
          <Button asChild size="sm"><Link to="/">回大厅</Link></Button>
        </AlertDescription>
      </Alert>
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <LoginProvider>
        <Toaster theme="light" richColors position="top-center" closeButton />
        <Routes>
          <Route element={<AppShell />}>
            <Route path="/" element={<Lobby />} />
            <Route path="/records" element={<Records />} />
            <Route path="/models" element={<Models />} />
            <Route path="/watch/match/:matchId" element={<WatchReplay />} />
            <Route path="/watch/:game/:sessionId" element={<Watch />} />
            <Route path="/profile" element={<Profile />} />
            <Route path="/friends" element={<Friends />} />
            <Route path="/admin" element={<Admin />} />
            <Route path="/notifications" element={<Notifications />} />
            <Route path="/games/ugc/:slug" element={<UgPlay />} />
            <Route path="/games/ugc/:slug/pvp" element={<UgPvp />} />
            {/* 13 G3：统一路由 /games/{slug}（静态内置路由优先，G4 删除专属页面后生效） */}
            <Route path="/games/:slug" element={<UgPlay />} />
            <Route path="/games/:slug/pvp" element={<UgPvp />} />
            <Route path="/ugc" element={<UgUpload />} />
            <Route path="*" element={<NotFound />} />
          </Route>
        </Routes>
      </LoginProvider>
    </BrowserRouter>
  );
}
