"""Play API: server-side authoritative game sessions (v1.0).

Design: docs/design/03（PvE/PvP 流程）+ 06（房间/匹配）。

    POST /api/v1/{game}/play/sessions          create/join (login required)
    GET  /api/v1/{game}/play/sessions/{id}     state/status (players or spectators)
    POST /api/v1/{game}/play/sessions/{id}/actions   submit actions -> advance tick
    POST /api/v1/{game}/play/sessions/{id}/leave     resign/abandon/cancel room
    GET  /api/v1/{game}/play/sessions/{id}/replay    replay log
    GET/POST /api/v1/{game}/play/rooms*        public room list / create / join (06 M1)
    GET  /api/v1/play/active                   my unfinished sessions (06 §7 U5)
    POST /api/v1/{game}/play/sessions/{id}/rematch   rematch, sides swapped (U7)
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

import matches
import sessions
from api_schemas import (
    ActiveSessionsResponse,
    CreateSessionResponse,
    GetSessionResponse,
    LeaveSessionResponse,
    RoomsResponse,
    SessionActionResponse,
    SessionReplay,
)
from auth import principal_from_request
from api_limits import rate_limit as _rate_limit
from registry import GAMES

router = APIRouter(tags=["play"])


class CreateSession(BaseModel):
    kind: str = Field(default="pve", pattern="^(pve|pvp)$",
                      description="pve（单人/打 AI，需登录）| pvp（人 vs 人，需登录）")
    seed: int | None = Field(default=None, description="固定地图/轨迹（可复现）")
    opponent: dict | None = Field(
        default=None,
        description="PvE 对手（声明 opponents 的游戏）：{\"type\":\"ai\",\"strategy\":\"…\"} | "
                    "{\"type\":\"model\",\"model_id\":N} | "
                    "{\"type\":\"external_bot\",\"url\":\"https://…\"}")
    controller: dict | None = Field(
        default=None,
        description="模型代打（声明模型契约的游戏）：{\"type\":\"model\",\"model_id\":N}，"
                    "随后 POST actions 时 actions 传 null")
    invite: str | None = Field(default=None,
                               description="pvp：加入指定邀请码的对局")
    mode: str | None = Field(default=None, pattern="^(ranked|casual)$",
                             description="pvp 计分模式；缺省=ranked（兼容老客户端）")
    visibility: str | None = Field(default=None,
                                   pattern="^(public|private)$",
                                   description="pvp 可见性；缺省=private（兼容老客户端）")
    settings: dict | None = Field(default=None,
                                  description="pvp 开局参数，v1 仅 {\"seed\": N}")
    side: str = Field(default="p0", pattern="^p[01]$",
                      description="pvp 加入时扮演哪一方")


class CreateRoom(BaseModel):
    mode: str = Field(default="casual", pattern="^(ranked|casual)$",
                      description="计分模式：ranked 结算 ELO / casual 不计分（D10 默认 casual）")
    visibility: str = Field(default="public", pattern="^(public|private)$",
                            description="public 进大厅公开列表 / private 仅凭邀请码")
    settings: dict | None = Field(default=None,
                                  description="开局参数，v1 仅 {\"seed\": N}")


class JoinRoom(BaseModel):
    invite: str | None = Field(default=None,
                               description="private 房间必须携带 6 位邀请码；public 免码")


class ActionsIn(BaseModel):
    actions: object = Field(description="该游戏动作：int / 指令列表（按游戏）")
    expected_tick: int | None = Field(
        default=None, ge=0,
        description="乐观并发：服务端当前 tick 必须等于该值，否则 409（防网络重试双推进）")


def _get(game: str, sid: str) -> sessions.PlaySession:
    sess = sessions.get_session(sid)
    if sess is None or sess.game != game:
        raise HTTPException(404, "session not found")
    return sess


def _require_owner(sess: sessions.PlaySession, principal: dict) -> None:
    """PvE sessions are private to their creator (play requires login)."""
    if sess.kind != "pvp" and principal.get("id") != sess.principal.get("id"):
        raise HTTPException(403, "不是你的对局")


@router.post("/api/v1/{game}/play/sessions",
             response_model=CreateSessionResponse,
             response_model_exclude_unset=True,
             summary="创建/加入游玩会话（PvE/PvP）")
def create_session(game: str, req: CreateSession, request: Request) -> dict:
    if game not in GAMES:
        raise HTTPException(404, f"unknown game {game!r}")
    principal = principal_from_request(request)
    if not principal.get("id"):
        raise HTTPException(401, "请先登录（游玩会话需要账号）")
    try:
        if req.kind == "pvp":
            sess = sessions.create_pvp_session(
                game, principal, req.invite, req.seed,
                mode=req.mode or "ranked",
                visibility=req.visibility or "private",
                settings=req.settings)
        else:
            sess = sessions.create_session(game, principal, req.seed,
                                           req.opponent, req.controller)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except PermissionError as e:
        raise HTTPException(429, str(e))
    out = {"session": sessions.public_session(sess)}
    if sess.kind == "pvp":
        out["invite"] = sess.invite
        out["side"] = sess.side_of(principal)
    return out


@router.get("/api/v1/{game}/play/sessions/{sid}",
            response_model=GetSessionResponse,
            response_model_exclude_unset=True,
            summary="查询会话状态（玩家/观战）")
def get_session(game: str, sid: str, request: Request) -> dict:
    sess = _get(game, sid)
    if sess.kind == "pvp":
        principal = principal_from_request(request)
        try:
            side = sess.side_of(principal)
        except PermissionError:
            side = None  # spectator view
        # 观战规则（06 §7）：public 房间与匹配撮合的对局公开可围观；
        # private 房间仅对局双方可读
        if side is None and sess.visibility == "private" and not sess.from_matchmaking:
            raise HTTPException(403, "私有对局不可观战")
        with sess.lock:
            sessions.pvp_poll(sess)
        _record_if_finished(sess)
    out = {"session": sessions.public_session(sess)}
    if sess.kind == "pvp":
        out["side"] = side
    return out


@router.post("/api/v1/{game}/play/sessions/{sid}/actions",
             response_model=SessionActionResponse,
             response_model_exclude_unset=True,
             summary="提交动作")
def act(game: str, sid: str, req: ActionsIn, request: Request) -> dict:
    # docs/design/02: play/actions 10 req/s（游客）/ 30 req/s（登录用户）
    _rate_limit(request, cap=10.0, user_cap=30.0,
                bucket="play", label="play API")
    sess = _get(game, sid)
    principal = principal_from_request(request)
    if sess.kind == "pvp":
        try:
            r = sessions.pvp_step(sess, principal, req.actions,
                                  expected_tick=req.expected_tick)
        except ValueError as e:
            raise HTTPException(400, str(e))
        except RuntimeError as e:
            raise HTTPException(409, str(e))
        except PermissionError:
            raise HTTPException(403, "你不是本对局的玩家")
        _record_if_finished(sess)
        body = {"state": r["state"], "tick": r["state"].get("tick", 0),
                "done": r.get("done", False), "winner": r.get("winner"),
                "cause": r.get("cause"), "advanced": r.get("advanced", False),
                "status": sess.status, "game_version": sess.game_version,
                "match_id": getattr(sess, "_match_id", None)}
        if r.get("waiting_for"):
            body["waiting_for"] = r["waiting_for"]
        return body
    _require_owner(sess, principal)
    try:
        nxt = sessions.step_session(sess, req.actions,
                                    expected_tick=req.expected_tick)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    _record_if_finished(sess)
    return {
        "state": nxt,
        "tick": nxt.get("tick", 0),
        "done": nxt.get("done", False),
        "winner": nxt.get("winner"),
        "cause": nxt.get("cause"),
        "reward": nxt.get("reward", 0.0),
        "status": sess.status,
        "game_version": sess.game_version,
        "match_id": getattr(sess, "_match_id", None),
    }


def _record_if_finished(sess) -> None:
    """Persist a finished session once; keep the match id for score claims."""
    if sess.status != "finished" or getattr(sess, "_recorded", False):
        return
    try:
        if sess.kind == "pvp":
            sess._match_id = matches.record_pvp_finish(sess)
        else:
            sess._match_id = matches.record_pve_finish(sess)
        sess._recorded = True
    except Exception:
        pass  # record failure must not break the game flow


@router.post("/api/v1/{game}/play/sessions/{sid}/leave",
             response_model=LeaveSessionResponse,
             response_model_exclude_unset=True,
             summary="认输/退出")
def leave(game: str, sid: str, request: Request) -> dict:
    sess = _get(game, sid)
    principal = principal_from_request(request)
    if sess.kind == "pvp":
        try:
            sessions.pvp_resign(sess, principal)
        except PermissionError:
            raise HTTPException(403, "你不是本对局的玩家")
        _record_if_finished(sess)
        return {"status": sess.status, "winner": sess.winner}
    _require_owner(sess, principal)
    sessions.leave_session(sess, "left")
    return {"status": sess.status}


@router.get("/api/v1/{game}/play/sessions/{sid}/replay",
            response_model=SessionReplay,
            response_model_exclude_unset=True,
            summary="会话回放（可包含进行中的部分轨迹）")
def replay(game: str, sid: str) -> dict:
    return sessions.session_replay(_get(game, sid))


@router.get("/api/v1/play/active", response_model=ActiveSessionsResponse,
            response_model_exclude_unset=True,
            summary="我的进行中对局（断线重连入口）")
def active(request: Request) -> dict:
    principal = principal_from_request(request)
    if not principal.get("id"):
        raise HTTPException(401, "请先登录")
    return {"sessions": sessions.active_sessions(principal)}


@router.post("/api/v1/{game}/play/sessions/{sid}/rematch",
             response_model=CreateSessionResponse,
             response_model_exclude_unset=True,
             summary="再来一局（互换先后手）")
def rematch(game: str, sid: str, request: Request) -> dict:
    if game not in GAMES:
        raise HTTPException(404, f"unknown game {game!r}")
    principal = principal_from_request(request)
    try:
        sess = sessions.rematch_session(game, principal, sid)
    except KeyError:
        raise HTTPException(404, "对局不存在")
    except ValueError as e:
        raise HTTPException(400, str(e))
    except PermissionError as e:
        raise HTTPException(403, str(e))
    return {"session": sessions.public_session(sess),
            "invite": sess.invite, "side": sess.side_of(principal)}


# ----------------------------------------------------------------- rooms
# 房间 = waiting 状态 PvP 会话的正式化（06 §4）。public 房间出现在大厅列表，
# private 房间凭邀请码加入；ranked 结算 ELO、casual 只落对局记录（D10）。

@router.get("/api/v1/{game}/play/rooms", response_model=RoomsResponse,
            summary="公开等待中房间列表")
def list_rooms(game: str, request: Request, mode: str | None = None) -> dict:
    if game not in GAMES:
        raise HTTPException(404, f"unknown game {game!r}")
    # 14 重构：公开房间列表对游客开放（大厅实时房间数依赖）；加入房间仍需登录
    if mode is not None and mode not in ("ranked", "casual"):
        raise HTTPException(400, "mode 必须是 ranked 或 casual")
    return {"rooms": sessions.list_public_rooms(game, mode)}


@router.post("/api/v1/{game}/play/rooms",
             response_model=CreateSessionResponse,
             response_model_exclude_unset=True,
             summary="创建房间")
def create_room(game: str, req: CreateRoom, request: Request) -> dict:
    if game not in GAMES:
        raise HTTPException(404, f"unknown game {game!r}")
    principal = principal_from_request(request)
    if not principal.get("id"):
        raise HTTPException(401, "请先登录（PvP 需要账号）")
    try:
        sess = sessions.create_pvp_session(game, principal, None, None,
                                           mode=req.mode,
                                           visibility=req.visibility,
                                           settings=req.settings)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except PermissionError as e:
        raise HTTPException(429, str(e))
    return {"session": sessions.public_session(sess),
            "invite": sess.invite, "side": "p0"}


@router.post("/api/v1/{game}/play/rooms/{sid}/join",
             response_model=CreateSessionResponse,
             response_model_exclude_unset=True,
             summary="加入房间")
def join_room(game: str, sid: str, req: JoinRoom, request: Request) -> dict:
    if game not in GAMES:
        raise HTTPException(404, f"unknown game {game!r}")
    principal = principal_from_request(request)
    if not principal.get("id"):
        raise HTTPException(401, "请先登录（PvP 需要账号）")
    try:
        sess = sessions.join_room_session(game, principal, sid, req.invite)
    except KeyError:
        raise HTTPException(404, "房间不存在")
    except ValueError as e:
        raise HTTPException(400, str(e))
    except PermissionError as e:
        raise HTTPException(429, str(e))
    return {"session": sessions.public_session(sess),
            "invite": sess.invite, "side": "p1"}
