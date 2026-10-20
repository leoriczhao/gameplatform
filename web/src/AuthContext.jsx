import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { toast } from "sonner";
import { post, getJson } from "./api.js";

const AuthContext = createContext(null);
const TOKEN_KEY = "gp_token";
const USER_KEY = "gp_user";
const GUEST_KEY = "gp_guest_token";

export function AuthProvider({ children }) {
  const [userToken, setUserToken] = useState(() => localStorage.getItem(TOKEN_KEY) || "");
  const [guestToken, setGuestToken] = useState(() => localStorage.getItem(GUEST_KEY) || "");
  const [authReady, setAuthReady] = useState(false);
  const [user, setUser] = useState(() => {
    // 只有存在用户 token 时 gp_user 才是可信登录态；否则是残留（token 过期/被清），
    // 会伪装成"已登录"但所有请求 401（2026-09-08 线上事故根因）
    if (!localStorage.getItem(TOKEN_KEY)) {
      localStorage.removeItem(USER_KEY);
      return null;
    }
    try { return JSON.parse(localStorage.getItem(USER_KEY) || "null"); } catch { return null; }
  });

  // effective token: user token wins, else the browser's guest identity
  const token = userToken || guestToken;

  // validate the stored user token once on boot; acquire a guest identity
  // otherwise (per-browser uuid, so shared NATs don't collide on caps)
  useEffect(() => {
    if (userToken) {
      getJson("/api/v1/auth/me", userToken)
        .then((d) => setUser(d.user))
        .catch(() => {
          setUserToken("");
          setUser(null);
          localStorage.removeItem(TOKEN_KEY);
          localStorage.removeItem(USER_KEY);   // 必须一起清，否则留下"僵尸登录态"
          toast.error("登录已过期，请重新登录");
        })
        .finally(() => setAuthReady(true));
      return;
    }
    if (!guestToken) {
      post("/api/v1/auth/guest")
        .then((d) => {
          if (d.token) {
            localStorage.setItem(GUEST_KEY, d.token);
            setGuestToken(d.token);
          }
        })
        .catch(() => { /* offline */ })
        .finally(() => setAuthReady(true));
    } else {
      setAuthReady(true);
    }
  }, [userToken, guestToken]);

  const persist = useCallback((t, u) => {
    setUserToken(t);
    setUser(u);
    localStorage.setItem(TOKEN_KEY, t);
    localStorage.setItem(USER_KEY, JSON.stringify(u));
  }, []);

  const login = useCallback(async (username, password) => {
    const d = await post("/api/v1/auth/login", { username, password });
    persist(d.token, d.user);
    return d.user;
  }, [persist]);

  const register = useCallback(async (username, password) => {
    const d = await post("/api/v1/auth/register", { username, password });
    persist(d.token, d.user);
    return d.user;
  }, [persist]);

  const logout = useCallback(() => {
    setUserToken("");
    setUser(null);
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
  }, []);

  const refreshUser = useCallback(async () => {
    if (!userToken) return null;
    try {
      const d = await getJson("/api/v1/auth/me", userToken);
      setUser(d.user);
      localStorage.setItem(USER_KEY, JSON.stringify(d.user));
      return d.user;
    } catch (e) {
      if (e && e.status === 401) {
        setUserToken("");
        setUser(null);
        localStorage.removeItem(TOKEN_KEY);
        localStorage.removeItem(USER_KEY);
      }
      return null;
    }
  }, [userToken]);

  return (
    <AuthContext.Provider value={{ token, user, authReady, login, register, logout, refreshUser }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
