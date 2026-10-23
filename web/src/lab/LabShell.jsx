import { useEffect, useMemo, useRef, useState } from "react";
import { Link, NavLink, useLocation, useNavigate } from "react-router-dom";
import {
  Bell,
  BookOpen,
  Box,
  Gamepad2,
  LayoutDashboard,
  LogOut,
  Moon,
  Search,
  Sun,
  Swords,
  Upload,
  UserRound,
  Users,
} from "lucide-react";
import { useAuth } from "../AuthContext.jsx";
import { useLabAuth } from "./AuthDialog.jsx";
import { useLabTheme } from "./ThemeContext.jsx";
import { getJson, usePlatformStatus } from "./api.js";
import { gameLabel } from "./format.js";
import { Button, IconButton, Pill } from "./ui.jsx";

const NAV = [
  { to: "/", label: "总览", icon: LayoutDashboard, end: true },
  { to: "/environments", label: "环境", icon: Gamepad2 },
  { to: "/models", label: "模型", icon: Box },
  { to: "/matches", label: "对局", icon: Swords },
  { to: "/ugc", label: "创作", icon: Upload },
];

const DOC_ITEM = { to: "/api.html", label: "API 文档", external: true, icon: BookOpen };

function crumbsFor(pathname) {
  if (pathname === "/") return ["总览"];
  if (pathname === "/environments") return ["环境"];
  if (pathname.startsWith("/environments/")) return ["环境", decodeURIComponent(pathname.split("/")[2] || "")];
  if (pathname === "/models") return ["模型"];
  if (pathname === "/matches") return ["对局"];
  if (pathname === "/records") return ["对局"];
  if (pathname.startsWith("/games/")) {
    const parts = pathname.split("/").filter(Boolean);
    const game = parts[1] ? decodeURIComponent(parts[1]) : "";
    return ["环境", game, parts.includes("pvp") ? "对战" : "试玩"];
  }
  if (pathname.startsWith("/watch/match/")) return ["对局", "回放"];
  if (pathname.startsWith("/watch/")) {
    const parts = pathname.split("/").filter(Boolean);
    return ["观战", decodeURIComponent(parts[2] || "")];
  }
  if (pathname === "/profile") return ["资料"];
  if (pathname === "/friends") return ["好友"];
  if (pathname === "/notifications") return ["通知"];
  if (pathname === "/ugc") return ["创作者工作台"];
  if (pathname === "/admin") return ["管理后台"];
  return ["实验室"];
}

function CommandPalette({ open, onClose, items: baseItems }) {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const inputRef = useRef(null);

  const items = useMemo(() => {
    const all = baseItems;
    const q = query.trim().toLowerCase();
    if (!q) return all;
    return all.filter(
      (item) => item.label.toLowerCase().includes(q) || item.to.toLowerCase().includes(q),
    );
  }, [query, baseItems]);

  useEffect(() => {
    if (!open) return undefined;
    setQuery("");
    setActive(0);
    const t = setTimeout(() => inputRef.current && inputRef.current.focus(), 20);
    const onKey = (event) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      clearTimeout(t);
      window.removeEventListener("keydown", onKey);
    };
  }, [open, onClose]);

  if (!open) return null;

  const pick = (item) => {
    if (!item) return;
    onClose();
    if (item.external) {
      window.location.href = item.to;
      return;
    }
    navigate(item.to);
  };

  const onInputKey = (event) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActive((i) => Math.min(items.length - 1, i + 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((i) => Math.max(0, i - 1));
    } else if (event.key === "Enter") {
      event.preventDefault();
      pick(items[active]);
    }
  };

  return (
    <div
      className="lab-palette-backdrop"
      onMouseDown={(event) => event.target === event.currentTarget && onClose()}
    >
      <div className="lab-palette" role="dialog" aria-modal="true" aria-label="命令面板">
        <input
          ref={inputRef}
          className="lab-palette__input"
          placeholder="跳转到…  环境 / 模型 / 对局 / 文档"
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
            setActive(0);
          }}
          onKeyDown={onInputKey}
        />
        <div className="lab-palette__list">
          {items.length === 0 ? (
            <div className="lab-palette__empty">没有匹配的页面</div>
          ) : (
            items.map((item, index) => {
              const Icon = item.icon;
              return (
                <button
                  type="button"
                  key={item.to}
                  className={`lab-palette__item${index === active ? " is-active" : ""}`}
                  onMouseEnter={() => setActive(index)}
                  onClick={() => pick(item)}
                >
                  <Icon size={14} />
                  {item.label}
                  <small>{item.external ? "DOCS" : item.to}</small>
                </button>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
}

export default function LabShell({ children }) {
  const location = useLocation();
  const navigate = useNavigate();
  const { user, token, authReady, logout } = useAuth();
  const { openAuth } = useLabAuth();
  const { theme, toggle } = useLabTheme();
  const status = usePlatformStatus(12000);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [unread, setUnread] = useState(0);
  const [activeSessions, setActiveSessions] = useState([]);
  const menuRef = useRef(null);

  const crumbs = crumbsFor(location.pathname);
  const isOverview = location.pathname === "/";
  const loggedIn = Boolean(user) && user.role !== "guest";
  const displayName = user ? user.nickname || user.username : "";
  const initial = displayName ? displayName.slice(0, 1).toUpperCase() : "?";

  useEffect(() => {
    const onKey = (event) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPaletteOpen((open) => !open);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    setMenuOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    if (!loggedIn || !token) {
      setActiveSessions([]);
      return undefined;
    }
    let cancelled = false;
    const load = async () => {
      try {
        const data = await getJson("/api/v1/play/active", token);
        if (!cancelled) setActiveSessions(data.sessions || []);
      } catch (e) {
        /* keep */
      }
    };
    load();
    const timer = setInterval(load, 20000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [loggedIn, token, location.pathname]);

  useEffect(() => {
    if (!loggedIn || !token) {
      setUnread(0);
      return undefined;
    }
    let cancelled = false;
    const load = async () => {
      try {
        const data = await getJson("/api/v1/notifications/unread", token);
        if (!cancelled) setUnread(data.unread || 0);
      } catch (e) {
        /* keep */
      }
    };
    load();
    const timer = setInterval(load, 60000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [loggedIn, token]);

  const commandItems = useMemo(() => {
    const extra = loggedIn
      ? [
          { to: "/profile", label: "个人资料", icon: UserRound },
          { to: "/friends", label: "好友", icon: Users },
          { to: "/notifications", label: "通知", icon: Bell },
          { to: "/ugc", label: "创作者工作台", icon: Upload },
        ]
      : [];
    const admin =
      loggedIn && user && user.role === "admin"
        ? [{ to: "/admin", label: "管理后台", icon: Box }]
        : [];
    return [...NAV, ...extra, ...admin, DOC_ITEM];
  }, [loggedIn, user]);

  useEffect(() => {
    if (!menuOpen) return undefined;
    const onDown = (event) => {
      if (menuRef.current && !menuRef.current.contains(event.target)) setMenuOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [menuOpen]);

  return (
    <div className="lab-app">
      <div className="lab-shell">
        <aside className="lab-rail">
          <Link to="/" className="lab-logo" aria-label="Stream 首页">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <circle cx="12" cy="12" r="2.2" fill="currentColor" />
              <ellipse cx="12" cy="12" rx="9.2" ry="4" stroke="currentColor" strokeWidth="1.6" />
              <ellipse cx="12" cy="12" rx="9.2" ry="4" stroke="currentColor" strokeWidth="1.6" transform="rotate(60 12 12)" />
              <ellipse cx="12" cy="12" rx="9.2" ry="4" stroke="currentColor" strokeWidth="1.6" transform="rotate(120 12 12)" />
            </svg>
          </Link>
          <nav className="lab-nav" aria-label="主导航">
            {NAV.map((item) => {
              const Icon = item.icon;
              return (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.end}
                  className={({ isActive }) => `lab-nav-item${isActive ? " is-active" : ""}`}
                >
                  <span className="lab-nav-item__icon">
                    <Icon size={18} />
                  </span>
                  <span>{item.label}</span>
                </NavLink>
              );
            })}
          </nav>
          <div className="lab-rail__bottom">
            <div className={`lab-api-dot${status.ready ? "" : " is-offline"}`} title={status.ready ? "服务就绪" : "服务检查失败"}>
              <i />
              <span>API</span>
            </div>
            <button
              type="button"
              className={`lab-avatar${loggedIn ? " lab-avatar--lime" : ""}`}
              title={loggedIn ? displayName : "登录"}
              onClick={() => (loggedIn ? navigate("/profile") : openAuth("login"))}
            >
              {loggedIn ? initial : <UserRound size={13} />}
            </button>
          </div>
        </aside>

        <div className="lab-main">
          <header className="lab-header">
            <div className="lab-breadcrumb">
              <span className="lab-breadcrumb__root">STREAM / LAB</span>
              <span className="lab-breadcrumb__sep">›</span>
              {crumbs.map((crumb, index) =>
                index === crumbs.length - 1 ? (
                  <span key={crumb} className="lab-breadcrumb__page">
                    {crumb || "—"}
                  </span>
                ) : (
                  <span key={`${crumb}-${index}`}>{crumb}</span>
                ),
              )}
            </div>
            <div className="lab-header__right">
              <button type="button" className="lab-search-btn" onClick={() => setPaletteOpen(true)}>
                <Search size={13} />
                <span className="lab-search-btn__text">搜索环境、模型…</span>
                <kbd className="lab-kbd">⌘K</kbd>
              </button>
              <a
                href="/api.html"
                target="_blank"
                rel="noreferrer"
                className="lab-btn lab-btn--outline lab-btn--sm"
              >
                <BookOpen size={13} />
                API 文档
              </a>
              {loggedIn ? (
                <button
                  type="button"
                  className="lab-icon-btn lab-icon-btn--bare"
                  onClick={() => navigate("/notifications")}
                  title={unread > 0 ? `通知（${unread} 条未读）` : "通知"}
                  style={{ position: "relative" }}
                >
                  <Bell size={15} />
                  {unread > 0 ? <span className="lab-bell-dot" aria-hidden="true" /> : null}
                </button>
              ) : null}
              <IconButton onClick={toggle} title={theme === "dark" ? "切换到亮色" : "切换到深色"} aria-label="切换主题">
                {theme === "dark" ? <Sun size={15} /> : <Moon size={15} />}
              </IconButton>
              <Pill tone={status.ready ? "green" : "neutral"} dot>
                {status.ready ? "API READY" : authReady ? "API OFFLINE" : "CONNECTING"}
              </Pill>
              {loggedIn ? (
                <div className="lab-user" ref={menuRef}>
                  <button type="button" className="lab-user" onClick={() => setMenuOpen((open) => !open)} style={{ border: 0, height: "auto", padding: 0, background: "transparent" }}>
                    <span className="lab-avatar lab-avatar--lime">{initial}</span>
                    <span className="lab-truncate" style={{ maxWidth: 110 }}>{displayName}</span>
                  </button>
                  {menuOpen ? (
                    <div className="lab-user-menu">
                      <Link to="/profile">
                        <UserRound size={13} /> 个人资料
                      </Link>
                      <Link to="/friends">
                        <Users size={13} /> 好友
                      </Link>
                      <Link to="/notifications">
                        <Bell size={13} /> 通知
                      </Link>
                      <Link to="/ugc">
                        <Upload size={13} /> 创作者工作台
                      </Link>
                      {user.role === "admin" ? (
                        <Link to="/admin">
                          <Box size={13} /> 管理后台
                        </Link>
                      ) : null}
                      <button
                        type="button"
                        onClick={() => {
                          logout();
                          setMenuOpen(false);
                        }}
                      >
                        <LogOut size={13} /> 退出登录
                      </button>
                    </div>
                  ) : null}
                </div>
              ) : (
                <Button size="sm" onClick={() => openAuth("login")} disabled={!authReady}>
                  {authReady ? "登录" : "连接中…"}
                </Button>
              )}
            </div>
          </header>

          <nav className="lab-mobile-nav" aria-label="移动端导航">
            {NAV.map((item) => {
              const Icon = item.icon;
              return (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.end}
                  className={({ isActive }) => (isActive ? "is-active" : "")}
                >
                  <Icon size={14} />
                  {item.label}
                </NavLink>
              );
            })}
            <a href="/api.html" target="_blank" rel="noreferrer">
              <BookOpen size={14} />
              文档
            </a>
          </nav>

          {activeSessions.length > 0 ? (
            <div className="lab-resume" role="status">
              <span className="lab-resume__label">进行中</span>
              {activeSessions.slice(0, 2).map((sess) => (
                <Link
                  key={sess.id}
                  to={
                    sess.kind === "pvp"
                      ? `/games/${sess.game}/pvp?resume=${sess.id}`
                      : `/games/${sess.game}?resume=${sess.id}`
                  }
                  className="lab-resume__item"
                >
                  <Swords size={12} />
                  <span>
                    {gameLabel(sess.game)} · {sess.kind === "pvp" ? "PvP" : "试玩"} · TICK{" "}
                    {sess.tick || 0}
                  </span>
                  <span className="lab-resume__go">继续 →</span>
                </Link>
              ))}
            </div>
          ) : null}

          <main className={`lab-content${isOverview ? " lab-content--overview" : ""}`}>{children}</main>
        </div>
      </div>
      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} items={commandItems} />
    </div>
  );
}
