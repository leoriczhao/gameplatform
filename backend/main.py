"""Stream backend — multi-user game platform (v1.0).

Serves the React frontend plus a JSON API:
    /api/v1/auth/*           accounts (register/login/JWT/guest)
    GET  /api/games          game catalog (lobby data source)
    GET  /api/health         platform health + per-game summary + ops metrics
    /api/openenv/{game}/*    official OpenEnv environment sessions
    GET/POST /api/{game}/... built-in AI, leaderboard per game
    /api/v1/*                play (sessions/rooms/matchmaking/watch), models,
                             matches, social, growth, ops/admin (docs/design/00-09)

Training algorithms run in the client; environment state is owned by OpenEnv
sessions. Game engines are shared with platform play and model matches. Sessions,
rooms, and queues are in-memory (D12); everything else persists in SQLite.
"""
from __future__ import annotations

import time
import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from admin_routes import admin_router, router as ops_router
from auth_routes import router as auth_router
from game_routes import make_game_router
from openenv_native import make_openenv_app
from matches_routes import ratings_router, router as match_router
from matchmaking_routes import router as matchmaking_router
from model_routes import router as model_router
from platform_api import router as platform_router
from play_routes import router as play_router
from social_routes import router as social_router
from stats_routes import router as stats_router
from ugc_routes import admin_router as ugc_admin_router, router as ugc_router

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR.parent / "static-docs"

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app):
    stop = threading.Event()
    threads = [threading.Thread(target=fn, args=(stop,), daemon=True)
               for fn in (_session_cleaner, _matchmaker_loop)]
    for thread in threads:
        thread.start()
    try:
        yield
    finally:
        stop.set()
        for thread in threads:
            thread.join(timeout=2)
        ugc_store.ugc_runner.stop_all()


app = FastAPI(
    title="Stream API",
    lifespan=lifespan,
    description=(
        "多游戏 RL 平台：OpenEnv 环境交互 + 前端游戏界面。\n\n"
        "- 游戏大厅：/\n"
        "- 游戏列表：GET /api/games\n"
        "- 环境：/api/openenv/{game}/ws（官方 OpenEnv WebSocket 协议）\n"
        "- 环境 Schema：/api/openenv/{game}/schema\n"
        "- 人类可读文档：/api.html · Swagger UI：/docs\n\n"
        "训练算法在调用方运行，环境状态由服务端会话持有。"
        "reset 后在同一 WebSocket 上 step；旧原生环境 HTTP 接口已移除。"
    ),
    version="1.0.0",
    # Docs routes are registered manually below so the Swagger/ReDoc assets
    # can be self-hosted (the default CDN jsdelivr is unreliable from CN).
    docs_url=None,
    redoc_url=None,
)

# Everything here is unauthenticated; CORS lets browser-based trainers work too.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 13 G3：不再有「内置游戏」——所有游戏（官方种子包 + 用户上传）一律经
# seed_loader/发布流程注册后，由 _mount_ugc_routes 动态挂载 /api/{slug}/* 路由。

# v1 auth (accounts) — new platform surface, see docs/design/02
app.include_router(auth_router)

# v1 play API (server-side sessions), see docs/design/03
app.include_router(play_router)

# v1 model hosting (ONNX upload/eval), see docs/design/04
app.include_router(model_router)

# v1 matches (PvP history + model-vs-model), see docs/design/03+04
app.include_router(match_router)
app.include_router(ratings_router)

# v1 quick matchmaking (06 §5 / v1.0-a M2)
app.include_router(matchmaking_router)

# v1 social (profile/friends/chat/notifications), v1.0-b
app.include_router(social_router)

# v1 growth/stats/leaderboards, v1.0-c
app.include_router(stats_router)

# v1 ops (announcements/reports/admin console), v1.0-d
app.include_router(ops_router)
app.include_router(admin_router)

# v1 UGC (user-uploaded games), docs/design/10-11
app.include_router(ugc_router)
app.include_router(ugc_admin_router)

app.include_router(platform_router)

# OpenEnv 环境协议（docs/api/openenv.md）：全局目录端点 + 每游戏 /api/openenv/{game}/*
import registry as _registry  # noqa: E402
from fastapi import APIRouter as _APIRouter  # noqa: E402

_openenv_root = _APIRouter(prefix="/api/openenv", tags=["openenv"])


@_openenv_root.get("/list_environments")
def openenv_list_environments() -> list[str]:
    """OpenEnv 兼容：列出所有可用环境（= 已注册游戏）。"""
    return [g.game_id for g in _registry.GAMES.values()]


app.include_router(_openenv_root)

# periodic session cleanup (abandoned/idle), daemon thread
import sessions as session_store  # noqa: E402
import matchmaking  # noqa: E402


def _session_cleaner(stop) -> None:
    while not stop.is_set():
        try:
            session_store.cleanup()
            ugc_store.ugc_runner.idle_cleanup()
        except Exception:
            logger.exception("session/worker cleanup failed")
        stop.wait(60)



# first-admin bootstrap (v1.0-d): ADMIN_USERNAME/ADMIN_PASSWORD at startup
import admin as admin_store  # noqa: E402
admin_store.bootstrap_admin()

# 游戏库（13 G3）：所有游戏 = 游戏包（官方种子 packaged-games/* + 用户上传），
# 统一走 ugc 管线；启动时播种官方包并挂回注册表（内存态，重启恢复）。
import ugc as ugc_store  # noqa: E402


def _mount_ugc_routes(adapter) -> None:
    # 游戏路由在运行时动态挂载，必须插到 catch-all 静态挂载（"/"）之前，
    # 否则静态处理器会吞掉 /api/{slug}/... 并对 POST 返回 405。
    before = len(app.routes)
    app.include_router(make_game_router(adapter),
                       prefix=f"/api/{adapter.game_id}")
    # OpenEnv 唯一环境入口：/api/openenv/{game_id}/*
    # 官方 openenv 栈：每个游戏一个 OpenEnv 服务器子应用（wire 由官方包负责）
    app.mount(f"/api/openenv/{adapter.game_id}",
              make_openenv_app(adapter.game_id))
    added = app.routes[before:]
    del app.routes[before:]
    idx = next((i for i, r in enumerate(app.routes)
                if getattr(r, "path", None) == "/"), len(app.routes))
    app.routes[idx:idx] = added


def _seed_bundled_games() -> None:
    """把 packaged-games/* 作为官方种子包播种（12 §4.2 / 13 G3）。
    系统作者无登录权限；同版本幂等，高版本自动升级。"""
    import io
    import zipfile
    pkg_root = BASE_DIR.parent / "packaged-games"
    if not pkg_root.is_dir():
        raise RuntimeError("packaged-games directory is missing")
    import auth as auth_store
    import platform_api
    owner_id = auth_store.official_author_id()
    expected = set()
    for d in sorted(pkg_root.iterdir()):
        if not d.is_dir() or not (d / "game.yaml").is_file():
            continue
        expected.add(d.name)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for p in sorted(d.rglob("*")):
                if p.is_dir() or "__pycache__" in p.parts:
                    continue
                zf.writestr(p.relative_to(d).as_posix(), p.read_bytes())
        try:
            data = buf.getvalue()
            meta = ugc_store.ugc_pack.validate_package(data, builtin_games=())["meta"]
            game = ugc_store.get_game_by_slug(meta["slug"])
            version = ugc_store.active_version(game["id"]) if game else None
            if not (game and game["status"] == "published" and version
                    and ugc_store._version_tuple(version["version"])
                    >= ugc_store._version_tuple(meta["version"])):
                game, version = ugc_store.seed_game(owner_id, data)
            print(f"seed_loader: {game['slug']} v{version['version']} 已发布",
                  flush=True)
        except Exception as e:
            raise RuntimeError(f"official game {d.name} initialization failed: {e}") from e
    if not expected:
        raise RuntimeError("no official game packages found")
    platform_api.EXPECTED_GAMES = expected


ugc_store.set_router_mounter(_mount_ugc_routes)
try:
    ugc_store.ensure_schema()
    _seed_bundled_games()
    ugc_store.load_published_into_registry()
    import platform_api
    platform_api.ready()
except Exception:
    ugc_store.ugc_runner.stop_all()
    logger.exception("platform initialization failed")
    raise


@app.exception_handler(ugc_store.ugc_runner.WorkerError)
async def worker_error(_request, exc):
    logger.error("game worker unavailable: %s", exc)
    return JSONResponse(status_code=503, content={"detail": str(exc)})


# matchmaking scanner: pairs queued players every SCAN_INTERVAL seconds
def _matchmaker_loop(stop) -> None:
    while not stop.is_set():
        try:
            matchmaking.tick()
        except Exception:
            logger.exception("matchmaking scan failed")
        stop.wait(matchmaking.SCAN_INTERVAL)




# ------------------------------------------------------------------ docs UI
# Swagger/ReDoc with self-hosted assets (static-docs/vendor/), no CDN dependency.
# Registered BEFORE the static mount so /docs and /redoc are not swallowed by it.

@app.get("/docs", include_in_schema=False)
async def swagger_ui() -> HTMLResponse:
    return get_swagger_ui_html(
        openapi_url="/openapi.json",
        title="Stream API - Swagger UI",
        swagger_js_url="/vendor/swagger-ui-bundle.js",
        swagger_css_url="/vendor/swagger-ui.css",
        swagger_favicon_url="/favicon.svg",
    )


@app.get("/redoc", include_in_schema=False)
async def redoc_ui() -> HTMLResponse:
    return get_redoc_html(
        openapi_url="/openapi.json",
        title="Stream API - ReDoc",
        redoc_js_url="/vendor/redoc.standalone.js",
        redoc_favicon_url="/favicon.svg",
    )


# ------------------------------------------------------------- static frontend
# Mounted last so /api/*, /docs and /redoc win over static files.

class _NoCacheStaticFiles(StaticFiles):
    """Static files with Cache-Control: no-cache.

    Cloudflare's default edge caching keys off file extensions (.js/.css get
    ~4h), which serves stale frontend builds after deploys. `no-cache` keeps
    Cloudflare from caching them at the edge while browsers still revalidate
    with ETag (cheap 304s).
    """

    async def get_response(self, path: str, scope) -> object:
        # Unknown API paths must never become static HTML or a method-only 405.
        if scope.get("path", "").startswith("/api/"):
            return JSONResponse(status_code=404, content={"detail": "Not Found"})
        resp = await super().get_response(path, scope)
        resp.headers["Cache-Control"] = "no-cache"
        return resp


# React SPA build output (web/ -> dist/). Present in the Docker image (built in
# a node stage); missing in dev, where we return a build hint.
WEB_DIST = BASE_DIR.parent / "web" / "dist"


def _spa_index() -> Path | None:
    p = WEB_DIST / "index.html"
    return p if p.exists() else None


@app.get("/", include_in_schema=False)
async def index_page() -> HTMLResponse:
    """Lobby: the React SPA when built (always true in production)."""
    spa = _spa_index()
    if spa:
        return FileResponse(spa, headers={"Cache-Control": "no-cache"})
    return HTMLResponse(
        "<p>frontend not built — run <code>cd web && npm run build</code> "
        "(or use the Docker image)</p>",
        headers={"Cache-Control": "no-cache"})


# SPA routes: every game page is served by the React app (built in Docker);
# without a build we return a build hint (dev).
# /watch/* (v1.0-a M4): live spectate + match replay pages
@app.get("/watch/match/{mid}", include_in_schema=False)
@app.get("/watch/match/{mid}/", include_in_schema=False)
@app.get("/watch/{game}/{sid}", include_in_schema=False)
@app.get("/watch/{game}/{sid}/", include_in_schema=False)
@app.get("/profile", include_in_schema=False)
@app.get("/profile/", include_in_schema=False)
@app.get("/friends", include_in_schema=False)
@app.get("/friends/", include_in_schema=False)
@app.get("/admin", include_in_schema=False)
@app.get("/admin/", include_in_schema=False)
@app.get("/notifications", include_in_schema=False)
@app.get("/notifications/", include_in_schema=False)
@app.get("/games/{slug}", include_in_schema=False)
@app.get("/games/{slug}/", include_in_schema=False)
@app.get("/games/{slug}/pvp", include_in_schema=False)
@app.get("/games/{slug}/pvp/", include_in_schema=False)
@app.get("/records/", include_in_schema=False)
@app.get("/records", include_in_schema=False)
@app.get("/models/", include_in_schema=False)
@app.get("/models", include_in_schema=False)
@app.get("/environments", include_in_schema=False)
@app.get("/environments/", include_in_schema=False)
@app.get("/environments/{slug}", include_in_schema=False)
@app.get("/environments/{slug}/", include_in_schema=False)
@app.get("/matches", include_in_schema=False)
@app.get("/matches/", include_in_schema=False)
# 14 重构 D27：/arena 破坏性移除（无跳转、无别名，直接 404）
async def spa_game_page(slug: str | None = None) -> HTMLResponse:
    spa = _spa_index()
    if spa:
        return FileResponse(spa, headers={"Cache-Control": "no-cache"})
    return HTMLResponse(
        "<p>frontend not built — run <code>cd web && npm run build</code></p>",
        headers={"Cache-Control": "no-cache"})


# 游戏页 SPA 路由（13 G3 统一）：/games/{slug} 单机页、/games/{slug}/pvp 对战页、
# /games/ugc/{slug}（旧 UGC 别名）、/ugc 作者工作台——都由 React 路由接管。
@app.get("/games/ugc/{slug}", include_in_schema=False)
@app.get("/games/ugc/{slug}/", include_in_schema=False)
@app.get("/games/ugc/{slug}/pvp", include_in_schema=False)
@app.get("/games/ugc/{slug}/pvp/", include_in_schema=False)
@app.get("/ugc", include_in_schema=False)
@app.get("/ugc/", include_in_schema=False)
async def spa_ugc_page(slug: str | None = None) -> HTMLResponse:
    spa = _spa_index()
    if spa:
        return FileResponse(spa, headers={"Cache-Control": "no-cache"})
    return HTMLResponse(
        "<p>frontend not built — run <code>cd web && npm run build</code></p>",
        headers={"Cache-Control": "no-cache"})


# SPA static assets (hashed JS/CSS emitted by vite build).
app.mount("/assets", _NoCacheStaticFiles(directory=str(WEB_DIST / "assets"),
                                         check_dir=False),
          name="spa-assets")


app.mount("/", _NoCacheStaticFiles(directory=str(FRONTEND_DIR), html=True),
          name="static")
