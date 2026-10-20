import { useEffect, useState } from "react";
import { Link, NavLink, Outlet } from "react-router-dom";
import {
  BellIcon, BrainCircuitIcon, Gamepad2Icon, LogOutIcon, HistoryIcon,
  UserIcon, UsersIcon, BookOpenIcon, ExternalLinkIcon, UploadIcon,
  LayoutGridIcon,
} from "lucide-react";
import { useAuth } from "../AuthContext.jsx";
import { getJson, post } from "../api.js";
import { useLogin } from "./LoginProvider.jsx";
import LevelBadge from "./LevelBadge.jsx";
import { Button } from "./ui/button.jsx";
import { Avatar, AvatarFallback } from "./ui/avatar.jsx";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel,
  DropdownMenuSeparator, DropdownMenuTrigger,
} from "./ui/dropdown-menu.jsx";
import { EmptyState } from "./ui/empty-state.jsx";
import { cn } from "../lib/utils.js";

/* CHANGE-20261014-rl-lab-ux：顶栏 = 大厅 · 模型托管 · API 文档 · 上传 · 战绩(降权) · 好友 · 资料；无 /arena */
const NAV = [
  { kind: "route", to: "/", label: "大厅", icon: LayoutGridIcon, end: true },
  { kind: "route", to: "/models", label: "模型托管", icon: BrainCircuitIcon, emphasis: true },
  { kind: "ext", href: "/api.html", label: "API 文档", icon: BookOpenIcon, emphasis: true },
  { kind: "route", to: "/ugc", label: "上传游戏", icon: UploadIcon },
  { kind: "route", to: "/records", label: "战绩", icon: HistoryIcon, deemphasized: true },
  { kind: "route", to: "/friends", label: "好友", icon: UsersIcon },
  { kind: "route", to: "/profile", label: "资料", icon: UserIcon },
];

function NavLinks() {
  return (
    <nav className="hidden items-center gap-0.5 md:flex">
      {NAV.map((item) => {
        const Icon = item.icon;
        if (item.kind === "ext") {
          return (
            <a
              key={item.href}
              href={item.href}
              target="_blank"
              rel="noreferrer"
              className={cn(
                "flex items-center gap-1 rounded-md px-2.5 py-1 text-sm transition-colors hover:bg-neutral-100",
                item.emphasis ? "font-semibold text-indigo-600" : "text-muted-foreground"
              )}
            >
              <Icon className="size-3.5" />
              {item.label}
              <ExternalLinkIcon className="size-3 opacity-60" />
            </a>
          );
        }
        return (
          <NavLink
            key={item.to}
            to={item.to}
            end={!!item.end}
            className={({ isActive }) => cn(
              "flex items-center gap-1 rounded-md px-2.5 py-1 text-sm transition-colors",
              item.deemphasized && "text-muted-foreground/70",
              item.emphasis && "font-semibold",
              isActive
                ? "bg-neutral-100 font-medium text-foreground"
                : item.emphasis
                  ? "text-indigo-600 hover:bg-neutral-100"
                  : "text-muted-foreground hover:bg-neutral-100 hover:text-foreground"
            )}
          >
            <Icon className="size-3.5" />
            {item.label}
          </NavLink>
        );
      })}
    </nav>
  );
}

function NotifBell() {
  const { user, token } = useAuth();
  const [unread, setUnread] = useState(0);
  const [items, setItems] = useState([]);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!user || !token) { setUnread(0); setItems([]); return undefined; }
    const load = async () => {
      try {
        const d = await getJson("/api/v1/notifications/unread", token);
        setUnread(d.unread || 0);
      } catch (e) { /* offline */ }
    };
    load();
    const t = setInterval(load, 15000);
    return () => clearInterval(t);
  }, [user, token]);

  const openList = async () => {
    try {
      const d = await getJson("/api/v1/notifications", token);
      setItems(d.items || []);
    } catch (e) { /* offline */ }
  };

  const markRead = async () => {
    try {
      await post("/api/v1/notifications/read", {}, token);
      setUnread(0);
      setItems((xs) => xs.map((x) => ({ ...x, read: true })));
    } catch (e) { /* offline */ }
  };

  if (!user) {
    return (
      <span className="hidden text-xs text-muted-foreground sm:inline">通知</span>
    );
  }
  return (
    <DropdownMenu open={open} onOpenChange={(v) => { setOpen(v); if (v) openList(); }}>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" aria-label="通知" className="relative size-8">
          <BellIcon className="size-4" />
          {unread > 0 && (
            <span className="absolute -top-0.5 -right-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-red-500 px-1 text-[10px] font-bold text-white shadow-sm">
              {unread > 99 ? "99+" : unread}
            </span>
          )}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-[330px]">
        <DropdownMenuLabel className="flex items-center justify-between text-foreground">
          <span className="text-sm font-semibold">通知</span>
          <button
            type="button"
            onClick={markRead}
            disabled={!unread}
            className="cursor-pointer text-xs text-indigo-600 hover:underline disabled:cursor-default disabled:opacity-40"
          >
            全部已读
          </button>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <div className="max-h-80 overflow-y-auto">
          {items.length ? items.map((n) => (
            <div key={n.id} className="border-b border-border px-2 py-2 last:border-0">
              <div className="text-[13px] leading-snug">{n.body}</div>
              <div className="mt-1 flex items-center justify-between">
                <span className="text-[11px] text-muted-foreground">
                  {new Date(n.created_at * 1000).toLocaleString("zh-CN", { hour12: false })}
                  {!n.read ? " · 未读" : ""}
                </span>
                {n.link ? <Link to={n.link} className="text-xs text-indigo-600 hover:underline">查看 →</Link> : null}
              </div>
            </div>
          )) : (
            <EmptyState title="暂无通知" className="py-8" />
          )}
        </div>
        <DropdownMenuSeparator />
        <DropdownMenuItem asChild className="justify-center text-muted-foreground">
          <Link to="/notifications">查看全部通知 →</Link>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function UserMenu() {
  const { user, logout } = useAuth();
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" className="h-8 gap-2 px-2">
          <Avatar className="size-6 bg-indigo-500">
            <AvatarFallback className="bg-transparent text-xs">
              {(user.nickname || user.username || "?").slice(0, 1).toUpperCase()}
            </AvatarFallback>
          </Avatar>
          <span className="max-w-24 truncate text-sm">{user.nickname || user.username}</span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-48">
        <DropdownMenuLabel className="text-xs">
          账号：{user.username}
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem asChild>
          <Link to="/profile"><UserIcon /> 我的资料</Link>
        </DropdownMenuItem>
        <DropdownMenuItem asChild>
          <Link to="/notifications"><BellIcon /> 通知</Link>
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem variant="destructive" onClick={logout}>
          <LogOutIcon /> 退出登录
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export default function AppShell() {
  const { user } = useAuth();
  const openLogin = useLogin();
  return (
    <div className="app-bg">
      <header className="sticky top-0 z-50 border-b border-border bg-background/90 backdrop-blur-xl">
        <div className="mx-auto flex h-12 w-full max-w-6xl items-center gap-3 px-3 sm:px-5">
          <Link to="/" className="group flex shrink-0 items-center gap-1.5">
            <span className="flex size-7 items-center justify-center rounded-md bg-indigo-600 shadow-sm transition-transform group-hover:scale-105">
              <Gamepad2Icon className="size-3.5 text-white" />
            </span>
            <span className="hidden text-[15px] font-bold tracking-wide sm:block">
              <span className="gradient-text">Stream</span>
            </span>
          </Link>
          <NavLinks />
          <div className="ml-auto flex items-center gap-1">
            <LevelBadge />
            <NotifBell />
            {user ? <UserMenu /> : (
              <Button size="sm" className="h-8 px-3" onClick={openLogin}>登录</Button>
            )}
          </div>
        </div>
      </header>
      <main>
        <Outlet />
      </main>
    </div>
  );
}
