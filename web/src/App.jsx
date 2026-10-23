import { BrowserRouter, Outlet, Routes, Route } from "react-router-dom";
import { Toaster } from "sonner";

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
import LabWatch from "./lab/pages/Watch.jsx";
import LabWatchReplay from "./lab/pages/WatchReplay.jsx";
import LabNotFound from "./lab/pages/NotFound.jsx";

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
              <Route path="/watch/match/:matchId" element={<LabWatchReplay />} />
              <Route path="/watch/:game/:sessionId" element={<LabWatch />} />
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
