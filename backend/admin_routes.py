"""Ops API (v1.0-d): public announcements, user reports, admin console."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

import admin
from auth_routes import _principal

router = APIRouter(tags=["ops"])
admin_router = APIRouter(tags=["admin"], prefix="/api/v1/admin")


def _require_user(principal: dict) -> dict:
    if principal.get("role") == "guest" or not principal.get("id"):
        raise HTTPException(401, "请先登录")
    return principal


def _require_admin(principal: dict) -> dict:
    user = _require_user(principal)
    if user.get("role") != "admin":
        raise HTTPException(403, "需要管理员权限")
    return user


class ReportIn(BaseModel):
    target_type: str = Field(description="user | model | match | chat | ugc_game | ugc_version")
    target_id: int = Field(ge=1, description="目标 id")
    reason: str | None = Field(default=None, max_length=300, description="举报理由")


class AnnouncementIn(BaseModel):
    body: str = Field(min_length=1, max_length=300, description="公告内容")


class StatusIn(BaseModel):
    status: str = Field(description="目标状态")


# ------------------------------------------------- public announcements

@router.get("/api/v1/announcements", summary="生效中的全站公告（公开）")
def announcements() -> dict:
    return {"items": admin.list_announcements(active_only=True)}


# -------------------------------------------------------------- reports

@router.post("/api/v1/reports", summary="提交举报（登录用户）")
def report(req: ReportIn, principal: dict = Depends(_principal)) -> dict:
    user = _require_user(principal)
    try:
        rep = admin.create_report(user["id"], req.target_type,
                                  req.target_id, req.reason or "")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"report": rep}


# ------------------------------------------------------------ admin console

@admin_router.get("/dashboard", summary="数据看板聚合")
def dashboard(principal: dict = Depends(_principal)) -> dict:
    _require_admin(principal)
    return admin.dashboard()


@admin_router.get("/users", summary="用户列表")
def users(principal: dict = Depends(_principal)) -> dict:
    _require_admin(principal)
    return {"users": admin.list_users()}


@admin_router.post("/users/{user_id}/status", summary="封禁/解封用户")
def user_status(user_id: int, req: StatusIn,
                principal: dict = Depends(_principal)) -> dict:
    admin_user = _require_admin(principal)
    try:
        ok = admin.set_user_status(user_id, req.status, admin_user["id"])
    except KeyError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not ok:
        raise HTTPException(404, "用户不存在")
    return {"updated": True}


@admin_router.get("/models", summary="全部模型列表")
def models(principal: dict = Depends(_principal)) -> dict:
    _require_admin(principal)
    return {"models": admin.list_models_all()}


@admin_router.post("/models/{model_id}/status", summary="模型下架/恢复")
def model_status(model_id: int, req: StatusIn,
                 principal: dict = Depends(_principal)) -> dict:
    _require_admin(principal)
    try:
        ok = admin.set_model_status(model_id, req.status)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not ok:
        raise HTTPException(404, "模型不存在")
    return {"updated": True}


@admin_router.get("/matches", summary="最近对局列表")
def matches(principal: dict = Depends(_principal)) -> dict:
    _require_admin(principal)
    return {"matches": admin.list_matches_all()}


@admin_router.get("/reports", summary="举报列表")
def reports(status: str | None = Query(None, pattern="^(open|resolved|dismissed)$"),
            principal: dict = Depends(_principal)) -> dict:
    _require_admin(principal)
    return {"reports": admin.list_reports(status)}


@admin_router.post("/reports/{rid}/status", summary="处理举报")
def report_status(rid: int, req: StatusIn,
                  principal: dict = Depends(_principal)) -> dict:
    _require_admin(principal)
    try:
        ok = admin.set_report_status(rid, req.status)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not ok:
        raise HTTPException(404, "举报不存在")
    return {"updated": True}


@admin_router.get("/announcements", summary="公告列表（含停用）")
def ann_list(principal: dict = Depends(_principal)) -> dict:
    _require_admin(principal)
    return {"items": admin.list_announcements(active_only=False)}


@admin_router.post("/announcements", summary="发布公告")
def ann_create(req: AnnouncementIn, principal: dict = Depends(_principal)) -> dict:
    _require_admin(principal)
    try:
        item = admin.create_announcement(req.body)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"announcement": item}


@admin_router.post("/announcements/{aid}/active", summary="启用/停用公告")
def ann_toggle(aid: int, req: StatusIn,
               principal: dict = Depends(_principal)) -> dict:
    _require_admin(principal)
    active = str(req.status).lower() in ("1", "true", "active", "on")
    if not admin.set_announcement_active(aid, active):
        raise HTTPException(404, "公告不存在")
    return {"updated": True}
