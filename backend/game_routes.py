"""Per-game platform HTTP routes: built-in AI and leaderboards.

Environment interaction is provided exclusively by the OpenEnv subapplication.
Leaderboards are read-only here: entries are written by the server when a v2
practice match settles (scores subscribes to match_finished, design 17 §8), so
there is no client score-submission endpoint.
"""
from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException, Query, Request
from pydantic import ValidationError

import registry
import scores
from api_limits import rate_limit


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

    # ------------------------------------------- leaderboard (server-written)
    @router.get("/scores")
    def top_scores(limit: int = Query(10, ge=1, le=100)) -> dict:
        cur = _cur()
        return {"items": scores.top(cur.game_id, limit)}

    return router
