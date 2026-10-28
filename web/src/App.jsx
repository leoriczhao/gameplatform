import { useEffect } from "react";
import { BrowserRouter, Navigate, Outlet, Routes, Route, useNavigate, useParams } from "react-router-dom";
import { Toaster } from "sonner";

import { useAuth } from "./AuthContext.jsx";
import { getJson } from "./api.js";

import { LabThemeProvider, useLabTheme } from "./lab/ThemeContext.jsx";
import { LabAuthProvider } from "./lab/AuthDialog.jsx";
import LabShell from "./lab/LabShell.jsx";
import Overview from "./lab/pages/Overview.jsx";
import Environments from "./lab/pages/Environments.jsx";
import Environment from "./lab/pages/Environment.jsx";
import LabModels from "./lab/pages/Models.jsx";
import LabMatches from "./lab/pages/Matches.jsx";
import LabPlay from "./lab/pages/Play.jsx";
import LabPvp from "./lab/pages/Pvp.jsx";
import LabProfile from "./lab/pages/Profile.jsx";
import LabFriends from "./lab/pages/Friends.jsx";
import LabNotifications from "./lab/pages/Notifications.jsx";
import LabUgcUpload from "./lab/pages/UgUpload.jsx";
import LabAdmin from "./lab/pages/Admin.jsx";
import LabNotFound from "./lab/pages/NotFound.jsx";
import Stage from "./stage/Stage.jsx";

function ThemedToaster() {
  const { theme } = useLabTheme();
  return (
    <Toaster
      theme={theme === "light" ? "light" : "dark"}
      richColors
      position="top-center"
      closeButton
    />
  );
}

/* 旧观战链接（M4）：v1 历史对局详情 API 保留；能映射到 v2 对局就把 uid
   换成舞台地址 /m/:uid，否则回对局列表。等鉴权就绪后再发请求（v1 详情需登录）。 */
function LegacyMatchRedirect() {
  const { matchId } = useParams();
  const navigate = useNavigate();
  const { token, authReady } = useAuth();

  useEffect(() => {
    if (!authReady) return undefined;
    let cancelled = false;
    (async () => {
      try {
        const data = await getJson(`/api/v1/matches/${matchId}`, token);
        if (cancelled) return;
        const uid = data?.match?.uid;
        navigate(uid ? `/m/${uid}` : "/matches", { replace: true });
      } catch (err) {
        if (!cancelled) navigate("/matches", { replace: true });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [matchId, token, authReady, navigate]);

  return (
    <div className="lab-loading">
      <span className="lab-spinner" aria-hidden="true" />
      <span>正在打开对局…</span>
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <LabThemeProvider>
        <LabAuthProvider>
          <ThemedToaster />
          <Routes>
            <Route
              element={
                <LabShell>
                  <Outlet />
                </LabShell>
              }
            >
              <Route path="/" element={<Overview />} />
              <Route path="/environments" element={<Environments />} />
              <Route path="/environments/:slug" element={<Environment />} />
              <Route path="/models" element={<LabModels />} />
              <Route path="/matches" element={<LabMatches />} />
              <Route path="/games/ugc/:slug" element={<LabPlay />} />
              <Route path="/games/ugc/:slug/pvp" element={<LabPvp />} />
              <Route path="/games/:slug" element={<LabPlay />} />
              <Route path="/games/:slug/pvp" element={<LabPvp />} />
              <Route path="/m/:id" element={<Stage />} />
              {/* 旧观战链接（M4）：v1 记录能映射 uid 就直达 /m/:uid，否则回对局列表 */}
              <Route path="/watch/match/:matchId" element={<LegacyMatchRedirect />} />
              <Route path="/watch/:game/:sessionId" element={<Navigate to="/matches" replace />} />
              <Route path="/profile" element={<LabProfile />} />
              <Route path="/friends" element={<LabFriends />} />
              <Route path="/notifications" element={<LabNotifications />} />
              <Route path="/ugc" element={<LabUgcUpload />} />
              <Route path="/admin" element={<LabAdmin />} />
              <Route path="/records" element={<LabMatches />} />
              <Route path="*" element={<LabNotFound />} />
            </Route>
          </Routes>
        </LabAuthProvider>
      </LabThemeProvider>
    </BrowserRouter>
  );
}
