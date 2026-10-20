"""Matchmaking API (06 §5 / v1.0-a M2): queue, cancel, status poll.

Both players poll GET status; the matched response carries the internal
PvP room id, which the client opens via /play/sessions/{id} (M1 rooms)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

import matchmaking
from auth import principal_from_request
from registry import GAMES

router = APIRouter(tags=["matchmaking"])


class QueueIn(BaseModel):
    mode: str = Field(default="ranked", pattern="^(ranked|casual)$",
                      description="ranked 结算 ELO / casual 不计分")


def _user(request: Request) -> dict:
    principal = principal_from_request(request)
    if not principal.get("id"):
        raise HTTPException(401, "请先登录（快速匹配需要账号）")
    return principal


@router.post("/api/v1/{game}/matchmaking/queue", summary="进入快速匹配队列")
def enqueue(game: str, req: QueueIn, request: Request) -> dict:
    if game not in GAMES:
        raise HTTPException(404, f"unknown game {game!r}")
    principal = _user(request)
    try:
        matchmaking.join_queue(game, principal, req.mode)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return matchmaking.queue_status(game, principal)


@router.delete("/api/v1/{game}/matchmaking/queue", summary="取消排队")
def dequeue(game: str, request: Request) -> dict:
    principal = _user(request)
    matchmaking.leave_queue(game, principal)
    return {"queued": False}


@router.get("/api/v1/{game}/matchmaking/status", summary="排队状态（轮询，2s）")
def status(game: str, request: Request) -> dict:
    principal = _user(request)
    return matchmaking.queue_status(game, principal)
