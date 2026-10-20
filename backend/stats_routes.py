"""Stats & leaderboards API (v1.0-c): my stats + per-game boards."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

import growth
from auth_routes import _principal
from registry import GAMES

router = APIRouter(tags=["stats"])


def _require_user(principal: dict) -> dict:
    if principal.get("role") == "guest" or not principal.get("id"):
        raise HTTPException(401, "请先登录")
    return principal


@router.get("/api/v1/stats/me", summary="我的战绩统计（含 ELO 走势）")
def stats_me(principal: dict = Depends(_principal)) -> dict:
    user = _require_user(principal)
    return growth.stats_for(user["id"])


@router.get("/api/v1/leaderboards/{game}", summary="排行榜（总榜 ELO / 周榜胜场）")
def leaderboard(game: str, scope: str = Query("total", pattern="^(total|weekly)$"),
                principal: dict = Depends(_principal)) -> dict:
    _require_user(principal)
    if game not in GAMES:
        raise HTTPException(404, f"unknown game {game!r}")
    items = growth.total_board(game) if scope == "total" \
        else growth.weekly_board(game)
    return {"game": game, "scope": scope, "items": items}
