"""Per-game platform HTTP routes: built-in AI and trusted leaderboards.

Environment interaction is provided exclusively by the OpenEnv subapplication.
"""
from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException, Query, Request
from pydantic import BaseModel, Field, ValidationError

import matches
import registry
import scores
from api_limits import rate_limit
from auth import principal_from_request


class ScoreIn(BaseModel):
    match_id: int = Field(
        description="已结束的 PvE 对局 id；分数由服务端从该对局读取，客户端不能自报")
    name: str | None = Field(default=None, min_length=1, max_length=24,
                             description="展示昵称，1-24 字符；缺省用账号昵称")


def make_game_router(adapter) -> APIRouter:
    router = APIRouter(tags=[adapter.game_id])
    def _cur(version=None):
        if adapter.game_id not in registry.GAMES:
            raise HTTPException(404, f"unknown game {adapter.game_id!r}")
        try:
            return registry.resolve(adapter.game_id, version)
        except registry.VersionUnavailable as e:
            raise HTTPException(409, str(e))

    # ------------------------------------------------------- built-in AI
    # NB: the request model is per-game, so it cannot be a typed route
    # parameter (FastAPI can't resolve closure type hints); we accept a
    # generic dict body and validate with the adapter's own pydantic model.
    ai_model = getattr(adapter, "ai_request_model", None)
    if ai_model is not None:

        @router.post("/ai/action")
        def ai_action(request: Request,
                      payload: dict = Body(description="game-specific payload")) -> dict:
            # docs/design/02: 游客/IP 30 req/s，登录用户 60 req/s（独立 bucket）
            rate_limit(request, cap=30.0, user_cap=60.0,
                        bucket="ai", label="ai API")
            try:
                req = ai_model.model_validate(payload)
            except ValidationError as e:
                raise HTTPException(400, f"invalid request: {e.errors()}")
            try:
                return _cur().ai_action(req.model_dump())
            except ValueError as e:
                raise HTTPException(400, str(e))

    # ------------------------------------------------------- leaderboard
    @router.get("/scores")
    def top_scores(limit: int = Query(10, ge=1, le=100)) -> dict:
        cur = _cur()
        return {"items": scores.top(cur.game_id, limit)}

    @router.post("/scores")
    def submit_score(score: ScoreIn, request: Request) -> dict:
        # docs/design/02: 游客/IP 1 req/s，登录用户 5 req/s（独立 bucket）
        rate_limit(request, cap=1.0, user_cap=5.0,
                    bucket="scores", label="scores API")
        cur = _cur()
        principal = principal_from_request(request)
        if not principal.get("id"):
            raise HTTPException(401, "请先登录（成绩来自服务端对局）")
        m = matches.get_match(score.match_id)
        if m is None:
            raise HTTPException(404, "对局不存在")
        if m["kind"] != "pve" or m["game"] != cur.game_id:
            raise HTTPException(400, "只有本游戏的 PvE 对局可以上榜")
        if m["status"] != "finished":
            raise HTTPException(400, "对局尚未结束")
        owner = next((p.get("user_id") for p in (m["players"] or [])
                      if p.get("user_id")), None)
        if owner != principal["id"]:
            raise HTTPException(403, "不是你的对局")
        result = m.get("result") or {}
        final = result.get("score")
        if final is None:
            raise HTTPException(400, "该对局没有可上榜的分数")
        lo, hi = cur.score_bounds
        if not (lo <= int(final) <= hi):
            raise HTTPException(400, f"score must be in [{lo}, {hi}] for this game")
        name = (score.name or principal.get("nickname")
                or principal.get("username") or "玩家")
        # 内置 AI 演示/模型代打由服务端判定，客户端不能自报
        mode = "custom" if result.get("controller") else "human"
        try:
            return scores.submit(cur.game_id, name, int(final), mode,
                                 user_id=principal["id"], match_id=m["id"])
        except ValueError as e:
            raise HTTPException(400, str(e))

    return router
