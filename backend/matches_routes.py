"""Match history API: 对局历史/详情 + ELO 积分榜（设计 17 §6）.

v2 Match（/api/v2/matches）是唯一对局协议；这里保留历史查询与积分榜，
同时读取 v2 记录和迁移前归档的 v1 行。模型对战挑战（POST /api/v1/matches）
与 v1 回放端点（GET /api/v1/matches/{id}/replay）在 M4 删除（设计 17 §9）。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

import matches
from api_schemas import MatchDetailResponse, MatchesResponse
from auth_routes import _principal

router = APIRouter(tags=["matches"], prefix="/api/v1/matches")
ratings_router = APIRouter(tags=["ratings"])


def _require_user(principal: dict) -> dict:
    if principal.get("role") == "guest" or not principal.get("id"):
        raise HTTPException(401, "请先登录")
    return principal


@router.get("", response_model=MatchesResponse,
            response_model_exclude_unset=True,
            summary="我的对局历史")
def my_matches(principal: dict = Depends(_principal)) -> dict:
    user = _require_user(principal)
    return {"matches": matches.list_matches(user["id"])}


@router.get("/{match_id}", response_model=MatchDetailResponse,
            response_model_exclude_unset=True,
            summary="对局详情（v2 记录带 uid，可链到 /m/:id）")
def get(match_id: int, principal: dict = Depends(_principal)) -> dict:
    _require_user(principal)
    m = matches.get_match(match_id)
    if m is None:
        raise HTTPException(404, "match not found")
    return {"match": m}


@ratings_router.get("/api/v1/ratings/{game}", summary="PvP 积分榜（ELO）")
def ratings(game: str, principal: dict = Depends(_principal)) -> dict:
    if principal.get("role") == "guest":
        raise HTTPException(401, "请先登录")
    return {"items": matches.top_ratings(game)}
