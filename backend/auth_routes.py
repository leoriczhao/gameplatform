"""Auth routes: /api/v1/auth/* — see docs/design/02-账号体系.md."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

import auth

router = APIRouter(tags=["auth"], prefix="/api/v1/auth")


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=24)
    password: str = Field(min_length=8, max_length=128)


def _principal(request: Request) -> dict:
    return auth.principal_from_request(request)


@router.post("/register", summary="注册（自动登录）")
def register(cred: Credentials, request: Request) -> dict:
    try:
        user, token = auth.register_user(cred.username, cred.password)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"token": token, "user": user}


@router.post("/login", summary="登录")
def login(cred: Credentials) -> dict:
    result = auth.login_user(cred.username, cred.password)
    if result is None:
        raise HTTPException(401, "用户名或密码错误")
    user, token = result
    return {"token": token, "user": user}


@router.post("/guest", summary="获取游客身份（PvE 有限功能）")
def guest(request: Request) -> dict:
    # each browser gets its own guest token (uuid identity), so shared NATs
    # don't collide on per-identity session caps
    import uuid as _uuid
    sub = f"guest-{_uuid.uuid4().hex}"
    token = auth.create_token(sub, "guest", auth.TOKEN_TTL_GUEST)
    return {"token": token,
            "user": {"id": None, "username": sub, "nickname": "游客",
                     "role": "guest", "status": "active"}}


@router.get("/me", summary="当前用户信息")
def me(principal: dict = Depends(_principal)) -> dict:
    if principal["role"] == "guest":
        raise HTTPException(401, "未登录（游客请用 /auth/guest 或注册）")
    return {"user": principal}
