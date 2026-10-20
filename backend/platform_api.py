"""Platform-level API: game catalog + health."""
from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException

from registry import sorted_games

router = APIRouter(tags=["platform"])
EXPECTED_GAMES: set[str] = set()


@router.get("/api/ready", summary="数据库和官方游戏执行器就绪检查")
def ready() -> dict:
    import sqlite3
    import auth
    import registry
    try:
        conn = sqlite3.connect(f"file:{auth.SCORES_DB}?mode=rw", uri=True)
        try:
            conn.execute("SELECT 1 FROM users LIMIT 1").fetchone()
        finally:
            conn.close()
        if not EXPECTED_GAMES:
            raise RuntimeError("official game catalog was not initialized")
        for slug in sorted(EXPECTED_GAMES):
            adapter = registry.resolve(slug)
            adapter._worker().request("info", timeout=1.)
    except Exception as exc:
        raise HTTPException(503, f"not ready: {exc}") from exc
    return {"status": "ready", "games": sorted(EXPECTED_GAMES)}


@router.get("/api/games", summary="游戏列表（大厅数据源）")
def list_games() -> dict:
    """返回所有已注册游戏的元数据；前端大厅据此渲染游戏卡片。"""
    return {
        "games": [
            {
                "id": g.game_id,
                "name": g.name,
                "description": g.description,
                "has_ai": getattr(g, "ai_request_model", None) is not None,
                "pvp_enabled": getattr(g, "pvp_enabled", False),
                "author": getattr(g, "author", None),
                "meta": getattr(g, "meta", None),
                "schema_url": f"/api/openenv/{g.game_id}/schema",
                "openenv_url": f"/api/openenv/{g.game_id}",
                "page_url": f"/games/{g.game_id}/",
                "score_bounds": list(g.score_bounds),
            }
            for g in sorted_games()
        ]
    }


@router.get("/api/health", summary="平台健康检查（v1.0-e 扩展）")
def health() -> dict:
    """服务探活 + 每游戏概要 + 运行指标（活跃会话数 / DB 大小）。"""
    import sessions as session_store
    import auth as auth_store
    db_size = 0
    try:
        db_size = auth_store.SCORES_DB.stat().st_size
    except OSError:
        pass
    return {
        "status": "ok",
        "games": {
            g.game_id: {
                "grid": g.info().get("grid"),
                "has_ai": getattr(g, "ai_request_model", None) is not None,
            }
            for g in sorted_games()
        },
        "active_sessions": session_store.active_session_count(),
        "db_size_bytes": db_size,
        "time": int(time.time()),
    }
