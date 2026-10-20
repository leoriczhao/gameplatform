"""Social API (v1.0-b): profile, friends, room chat, notifications.

Design: docs/design/00 模块 B/G + 07 §6-b；D14 聊天轮询+落库。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

import sessions
import social
from auth_routes import _principal

router = APIRouter(tags=["social"])


def _require_user(principal: dict) -> dict:
    if principal.get("role") == "guest" or not principal.get("id"):
        raise HTTPException(401, "请先登录")
    return principal


class ProfileIn(BaseModel):
    nickname: str | None = Field(default=None, description="昵称 1-24 字符")
    avatar: str | None = Field(default=None, description="头像（emoji/短文本，≤16 字符）")
    signature: str | None = Field(default=None, description="个性签名 ≤120 字符")


class FriendIn(BaseModel):
    username: str = Field(min_length=1, max_length=24, description="对方的用户名")


class ChatIn(BaseModel):
    text: str = Field(min_length=1, max_length=500, description="消息内容")


@router.get("/api/v1/profile", summary="我的资料")
def get_profile(principal: dict = Depends(_principal)) -> dict:
    user = _require_user(principal)
    return {"profile": social.get_profile(user["id"])}


@router.put("/api/v1/profile", summary="修改资料（昵称/头像/签名）")
def put_profile(req: ProfileIn, principal: dict = Depends(_principal)) -> dict:
    user = _require_user(principal)
    try:
        profile = social.update_profile(user["id"], req.nickname, req.avatar,
                                        req.signature)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"profile": profile}
@router.get("/api/v1/friends", summary="好友列表")
def friends(principal: dict = Depends(_principal)) -> dict:
    user = _require_user(principal)
    items = social.list_friends(user["id"])
    online_ids = sessions.online_user_ids()
    for f in items:
        f["in_game"] = f["id"] in online_ids
    return {"friends": items}


@router.post("/api/v1/friends", summary="添加好友（按用户名，直接互加）")
def add_friend(req: FriendIn, principal: dict = Depends(_principal)) -> dict:
    user = _require_user(principal)
    try:
        friend = social.add_friend(user["id"], req.username)
    except KeyError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"friend": friend}


@router.delete("/api/v1/friends/{friend_id}", summary="删除好友")
def del_friend(friend_id: int, principal: dict = Depends(_principal)) -> dict:
    user = _require_user(principal)
    social.remove_friend(user["id"], friend_id)
    return {"removed": True}


@router.get("/api/v1/{game}/play/sessions/{sid}/chat", summary="房间聊天（since 游标轮询）")
def chat_get(game: str, sid: str, since: int = Query(0, ge=0),
             principal: dict = Depends(_principal)) -> dict:
    user = _require_user(principal)
    sess = sessions.get_session(sid)
    if sess is None or sess.kind != "pvp" or sess.game != game:
        raise HTTPException(404, "对局不存在")
    try:
        sess.side_of(user)
    except PermissionError:
        raise HTTPException(403, "仅对局双方可以在房间聊天")
    msgs, next_since = social.chat_since(sid, since)
    return {"messages": msgs, "next_since": next_since}


@router.post("/api/v1/{game}/play/sessions/{sid}/chat", summary="发送房间聊天")
def chat_post(game: str, sid: str, req: ChatIn,
              principal: dict = Depends(_principal)) -> dict:
    user = _require_user(principal)
    sess = sessions.get_session(sid)
    if sess is None or sess.kind != "pvp" or sess.game != game:
        raise HTTPException(404, "对局不存在")
    try:
        sess.side_of(user)
    except PermissionError:
        raise HTTPException(403, "仅对局双方可以在房间聊天")
    try:
        msg = social.chat_send(sid, user["id"], req.text)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"message": msg}
@router.get("/api/v1/notifications", summary="我的通知列表")
def notifications(principal: dict = Depends(_principal)) -> dict:
    user = _require_user(principal)
    return {"items": social.list_notifications(user["id"]),
            "unread": social.unread_count(user["id"])}


@router.get("/api/v1/notifications/unread", summary="未读通知数（铃铛红点）")
def unread(principal: dict = Depends(_principal)) -> dict:
    user = _require_user(principal)
    return {"unread": social.unread_count(user["id"])}


@router.post("/api/v1/notifications/read", summary="全部标记已读")
def read_all(principal: dict = Depends(_principal)) -> dict:
    user = _require_user(principal)
    social.mark_all_read(user["id"])
    return {"unread": 0}




