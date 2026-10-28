"""Match API v2 (docs/design/17 §5): commands over REST, results over SSE.

    POST /api/v2/matches                          create {game, seats?, mode?, visibility?, settings?}
    GET  /api/v2/matches?game&mode                lobby: waiting public rooms
    GET  /api/v2/me/matches                       my live matches (reconnect)
    GET  /api/v2/matches/{id}                     snapshot (MatchView)
    GET  /api/v2/matches/{id}/stream              SSE event stream (Last-Event-ID resumes)
    GET  /api/v2/matches/{id}/frames?from&limit   frame history (timeline, replay)
    POST /api/v2/matches/{id}/seats/{seat}/join   {invite?}
    POST /api/v2/matches/{id}/actions             {tick, action} → 202 {seq}
    POST /api/v2/matches/{id}/controller          {seat, controller}
    POST /api/v2/matches/{id}/resign
    POST /api/v2/matches/{id}/rematch
    GET/POST /api/v2/matches/{id}/chat            room chat (players only; polled)
    POST/DELETE /api/v2/{game}/matchmaking/queue, GET .../status

Commands return an acknowledgement; every state change reaches clients as
events on the stream. Errors carry a machine-readable ``code`` (§5.1).
"""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

import match_engine as engine
import matches as store
import matchmaking
import social
from api_limits import rate_limit
from auth import principal_from_request

router = APIRouter(tags=["matches-v2"])
PING_S = 15.0          # keeps tunnels from closing idle streams; clock-skew sample
FRAMES_PAGE = 500


class CreateIn(BaseModel):
    game: str
    seats: list[dict] | None = Field(default=None, description="[{seat, occupant: \"me\"|null, controller}]")
    mode: str | None = Field(default=None, description="practice | casual | ranked")
    visibility: str | None = Field(default=None, description="public | unlisted | private")
    settings: dict | None = Field(default=None, description="{seed}")


class JoinIn(BaseModel):
    invite: str | None = None


class ActionIn(BaseModel):
    tick: int = Field(ge=0, description="the tick this action is for (idempotency key)")
    action: object = Field(description="game action (int / command list …)")


class ControllerIn(BaseModel):
    seat: str
    controller: dict


class ChatIn(BaseModel):
    text: str = Field(min_length=1, max_length=500)


class QueueIn(BaseModel):
    mode: str = Field(default="casual", pattern="^(ranked|casual)$")


def _err(e: engine.MatchError) -> HTTPException:
    return HTTPException(e.status, e.detail())


def _user(request: Request) -> dict:
    principal = principal_from_request(request)
    if not principal.get("id"):
        raise HTTPException(401, {"code": "login_required", "message": "请先登录"})
    return principal


def _live(uid: str) -> engine.Match:
    m = engine.get_live(uid)
    if m is None:
        raise HTTPException(404, {"code": "not_live", "message": "对局不在进行中"})
    return m


def _readable(uid: str, principal: dict):
    """(live match | None, record | None) the caller may read; 404/403 otherwise."""
    m = engine.get_live(uid)
    if m is not None:
        if not engine.can_read(m.visibility, bool(m.seat_of(principal.get("id")))):
            raise HTTPException(403, {"code": "private", "message": "私有对局只有双方可以查看"})
        return m, None
    rec = store.get_v2(uid)
    if rec is None:
        raise HTTPException(404, {"code": "not_found", "message": "对局不存在"})
    seated = any(p.get("user_id") == principal.get("id") for p in rec["players"])
    if not engine.can_read(rec["visibility"], seated):
        raise HTTPException(403, {"code": "private", "message": "私有对局只有双方可以查看"})
    return None, rec


def _call(fn, *args):
    try:
        return fn(*args)
    except engine.MatchError as e:
        raise _err(e)


# ------------------------------------------------------------------ create / list

@router.post("/api/v2/matches", status_code=201, summary="创建对局")
def create(body: CreateIn, request: Request) -> dict:
    principal = _user(request)
    m = _call(engine.create_match, principal, body.model_dump())
    return m.view(principal["id"])


@router.get("/api/v2/matches", summary="大厅：等待中的公开房间")
def lobby(game: str, mode: str | None = Query(None, pattern="^(ranked|casual)$")) -> dict:
    return {"rooms": engine.lobby(game, mode)}


@router.get("/api/v2/me/matches", summary="我的进行中对局（重连入口）")
def my_matches(request: Request) -> dict:
    return {"matches": engine.my_live(_user(request)["id"])}


# ------------------------------------------------------------------ reads

@router.get("/api/v2/matches/{uid}", summary="对局快照（MatchView）")
def snapshot(uid: str, request: Request) -> dict:
    principal = principal_from_request(request)
    m, rec = _readable(uid, principal)
    return m.view(principal.get("id")) if m else engine.record_view(rec, principal.get("id"))


@router.get("/api/v2/matches/{uid}/frames", summary="帧历史（时间线 / 回放）")
def frames(uid: str, request: Request, start: int = Query(0, ge=0, alias="from"),
           limit: int = Query(FRAMES_PAGE, ge=1, le=FRAMES_PAGE)):
    m, rec = _readable(uid, principal_from_request(request))
    if m is not None:
        with m.lock:
            all_frames, sealed, visibility = list(m.frames), False, m.visibility
    else:
        all_frames = store.read_frames(rec["frames"]) if rec.get("frames") else []
        sealed, visibility = True, rec["visibility"]
    page = all_frames[start:start + limit]
    nxt = start + len(page)
    body = {"frames": page, "next": nxt if nxt < len(all_frames) else None,
            "total": len(all_frames)}
    headers = ({"Cache-Control": "public, max-age=86400"}
               if sealed and visibility != "private" else {"Cache-Control": "no-store"})
    return JSONResponse(body, headers=headers)


def _sse(event: dict) -> str:
    return (f"id: {event['seq']}\nevent: {event['type']}\n"
            f"data: {json.dumps(event, ensure_ascii=False, separators=(',', ':'))}\n\n")


@router.get("/api/v2/matches/{uid}/stream", summary="对局事件流（SSE）")
async def stream(uid: str, request: Request, since: int | None = Query(None, ge=0)):
    principal = await run_in_threadpool(principal_from_request, request)
    user_id = principal.get("id")
    m, rec = await run_in_threadpool(_readable, uid, principal)
    last = request.headers.get("last-event-id")
    cursor = int(last) if last and last.isdigit() else since

    if m is None:   # no longer live: one snapshot, then the stream ends
        view = await run_in_threadpool(engine.record_view, rec, user_id)

        async def once():
            yield _sse({**view, "type": "snapshot", "seq": 0})
        return StreamingResponse(once(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache"})

    async def events():
        loop = asyncio.get_running_loop()
        wake = asyncio.Event()
        m.log.listen(loop, wake)
        await run_in_threadpool(m.connect, user_id)
        try:
            pos = cursor
            backlog = m.log.since(pos) if pos is not None else None
            if backlog is None:
                view = await run_in_threadpool(m.view, user_id)
                pos = view["seq"]
                yield _sse({**view, "type": "snapshot"})
            else:
                for e in backlog:
                    pos = e["seq"]
                    yield _sse(e)
            while engine.get_live(uid) is m:
                if await request.is_disconnected():
                    break
                try:
                    await asyncio.wait_for(wake.wait(), timeout=PING_S)
                except asyncio.TimeoutError:
                    yield f"event: ping\ndata: {json.dumps({'server_time': engine._now_ms()})}\n\n"
                    continue
                wake.clear()
                items = m.log.since(pos)
                if items is None:   # fell behind the retained log: resync
                    view = await run_in_threadpool(m.view, user_id)
                    pos = view["seq"]
                    yield _sse({**view, "type": "snapshot"})
                    continue
                for e in items:
                    pos = e["seq"]
                    yield _sse(e)
        finally:
            # Synchronous on purpose: after a client disconnect the stream is
            # cancelled, and anyio cancels every later await in this block too.
            m.log.unlisten(loop, wake)
            m.disconnect(user_id)

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ------------------------------------------------------------------ commands

@router.post("/api/v2/matches/{uid}/seats/{seat}/join", summary="入座")
def join(uid: str, seat: str, body: JoinIn, request: Request) -> dict:
    principal = _user(request)
    m = _live(uid)
    _call(m.join, principal, seat, body.invite)
    return m.view(principal["id"])


@router.post("/api/v2/matches/{uid}/actions", status_code=202, summary="提交本 tick 的动作")
def act(uid: str, body: ActionIn, request: Request) -> dict:
    rate_limit(request, cap=10.0, user_cap=30.0, bucket="play", label="play API")
    principal = _user(request)
    seq = _call(_live(uid).submit, principal, body.tick, body.action)
    return {"accepted": True, "seq": seq}


@router.post("/api/v2/matches/{uid}/controller", summary="切换座位托管（练习局）")
def controller(uid: str, body: ControllerIn, request: Request) -> dict:
    principal = _user(request)
    m = _live(uid)
    _call(m.set_controller, principal, body.seat, body.controller)
    return m.view(principal["id"])


@router.post("/api/v2/matches/{uid}/resign", summary="认输 / 取消房间")
def resign(uid: str, request: Request) -> dict:
    principal = _user(request)
    m = _live(uid)
    _call(m.resign, principal)
    return {"status": m.status, "result": m.result}


@router.post("/api/v2/matches/{uid}/rematch", summary="再来一局（发起或接受）")
def rematch(uid: str, request: Request) -> dict:
    return _call(_live(uid).offer_rematch, _user(request))


# ------------------------------------------------------------------ chat

def _require_player(uid: str, principal: dict) -> None:
    m, rec = _readable(uid, principal)
    seated = (m.seat_of(principal["id"]) if m else
              any(p.get("user_id") == principal["id"] for p in rec["players"]))
    if not seated:
        raise HTTPException(403, {"code": "not_your_seat", "message": "仅对局双方可以聊天"})


@router.get("/api/v2/matches/{uid}/chat", summary="对局聊天（since 游标轮询）")
def chat_get(uid: str, request: Request, since: int = Query(0, ge=0)) -> dict:
    principal = _user(request)
    _require_player(uid, principal)
    msgs, next_since = social.chat_since(f"m:{uid}", since)
    return {"messages": msgs, "next_since": next_since}


@router.post("/api/v2/matches/{uid}/chat", summary="发送对局聊天")
def chat_post(uid: str, body: ChatIn, request: Request) -> dict:
    principal = _user(request)
    _require_player(uid, principal)
    try:
        return {"message": social.chat_send(f"m:{uid}", principal["id"], body.text)}
    except ValueError as e:
        raise HTTPException(400, {"code": "bad_message", "message": str(e)})


# ------------------------------------------------------------------ matchmaking

@router.post("/api/v2/{game}/matchmaking/queue", summary="进入快速匹配")
def enqueue(game: str, body: QueueIn, request: Request) -> dict:
    principal = _user(request)
    try:
        matchmaking.join_queue(game, principal, body.mode, api="v2")
    except (ValueError, PermissionError) as e:
        raise HTTPException(400, {"code": "bad_queue", "message": str(e)})
    matchmaking.try_match()
    return matchmaking.queue_status(game, principal)


@router.delete("/api/v2/{game}/matchmaking/queue", summary="取消匹配")
def dequeue(game: str, request: Request) -> dict:
    return {"removed": matchmaking.leave_queue(game, _user(request))}


@router.get("/api/v2/{game}/matchmaking/status", summary="匹配状态")
def queue_status(game: str, request: Request) -> dict:
    return matchmaking.queue_status(game, _user(request))
