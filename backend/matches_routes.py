"""Match API: PvP history + model-vs-model challenges.

Design: docs/design/03（PvP 流程）与 04（模型对战）."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import matches
from api_schemas import (
    CreateMatchResponse,
    MatchDetailResponse,
    MatchesResponse,
    MatchReplayResponse,
)
from auth_routes import _principal

router = APIRouter(tags=["matches"], prefix="/api/v1/matches")
ratings_router = APIRouter(tags=["ratings"])


class CreateMatch(BaseModel):
    game: str = Field(min_length=1, max_length=40,
                      description="游戏 slug（必填，需声明模型契约）")
    model_a: int = Field(description="你的模型 id")
    model_b: object = Field(
        description="对手：模型 id（int）或内置 AI 如 \"ai:light_rush\"")


def _require_user(principal: dict) -> dict:
    if principal.get("role") == "guest" or not principal.get("id"):
        raise HTTPException(401, "请先登录")
    return principal


@router.post("", response_model=CreateMatchResponse,
             summary="创建模型 vs 模型异步对战")
def create(req: CreateMatch, principal: dict = Depends(_principal)) -> dict:
    user = _require_user(principal)
    try:
        match_id = matches.create_model_match(req.game, user, req.model_a,
                                              req.model_b)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"match_id": match_id}


@router.get("", response_model=MatchesResponse,
            response_model_exclude_unset=True,
            summary="我的对局列表")
def my_matches(principal: dict = Depends(_principal)) -> dict:
    user = _require_user(principal)
    return {"matches": matches.list_matches(user["id"])}


@router.get("/{match_id}", response_model=MatchDetailResponse,
            response_model_exclude_unset=True,
            summary="对局详情（含回放）")
def get(match_id: int, principal: dict = Depends(_principal)) -> dict:
    _require_user(principal)
    m = matches.get_match(match_id)
    if m is None:
        raise HTTPException(404, "match not found")
    return {"match": m}




@router.get("/{match_id}/replay", response_model=MatchReplayResponse,
            response_model_exclude_unset=True,
            summary="已完成对局回放（公开只读，分享链接用）")
def replay(match_id: int) -> dict:
    """Public replay endpoint: no auth so share links open directly (06 §7)."""
    r = matches.get_match_replay(match_id)
    if r is None:
        raise HTTPException(404, "回放不存在（仅已结束的对局）")
    return {"replay": r}


@ratings_router.get("/api/v1/ratings/{game}", summary="PvP 积分榜（ELO）")
def ratings(game: str, principal: dict = Depends(_principal)) -> dict:
    if principal.get("role") == "guest":
        raise HTTPException(401, "请先登录")
    return {"items": matches.top_ratings(game)}
