"""UGC API (11 P3): author workspace, public directory, admin review console.

Design: docs/design/10 §7。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field

import ugc
import ugc_assets
import ugc_pack
from admin_routes import _require_admin
from auth_routes import _principal

router = APIRouter(tags=["ugc"])
admin_router = APIRouter(tags=["ugc-admin"], prefix="/api/v1/admin/ugc")


def _require_user(principal: dict) -> dict:
    if principal.get("role") == "guest" or not principal.get("id"):
        raise HTTPException(401, "请先登录")
    return principal


class NoteIn(BaseModel):
    note: str = Field(min_length=1, max_length=500, description="审核意见/原因")


class ReasonIn(BaseModel):
    reason: str = Field(min_length=1, max_length=200, description="暂停/熔断原因")


class RollbackIn(BaseModel):
    version_id: int = Field(ge=1, description="目标版本 id")


class RendererIn(BaseModel):
    enabled: bool = Field(description="是否开启沙箱渲染器（16 §5.1）")


def _read_upload(file: UploadFile) -> bytes:
    data = file.file.read()
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(400, "包超过 20MB 限制")
    return data


def _call(fn, *args):
    """统一错误映射：ValueError→400，KeyError→404，UGCError→400。"""
    try:
        return fn(*args)
    except ugc_pack.UGCError as e:
        raise HTTPException(400, str(e))
    except KeyError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


# --------------------------------------------------------------- author face

@router.post("/api/v1/ugc/games", summary="上传新游戏（草稿，配额内）")
def create_game(file: UploadFile = File(...), changelog: str = Form(""),
                principal: dict = Depends(_principal)) -> dict:
    user = _require_user(principal)
    game, version = _call(ugc.create_game, user["id"],
                          _read_upload(file), changelog or "")
    return {"game": game, "version": version}


@router.get("/api/v1/ugc/games", summary="我的游戏 / 公开目录")
def list_games(status: str | None = Query(None, pattern="^(published|all)$"),
               principal: dict = Depends(_principal)) -> dict:
    if status == "published":
        return {"games": ugc.list_public_games()}
    user = _require_user(principal)
    if status == "all":
        return {"games": ugc.list_my_games(user["id"])}
    return {"games": ugc.list_my_games(user["id"])}


@router.post("/api/v1/ugc/games/{gid}/versions", summary="上传新版本（版本号递增）")
def add_version(gid: int, file: UploadFile = File(...),
                changelog: str = Form(""),
                principal: dict = Depends(_principal)) -> dict:
    user = _require_user(principal)
    game, version = _call(ugc.add_version, user["id"], gid,
                          _read_upload(file), changelog or "")
    return {"game": game, "version": version}


@router.post("/api/v1/ugc/games/{gid}/submit", summary="提交审核")
def submit(gid: int, principal: dict = Depends(_principal)) -> dict:
    user = _require_user(principal)
    return {"game": _call(ugc.submit, gid, user["id"])}


@router.post("/api/v1/ugc/games/{gid}/unpublish", summary="作者自行下架")
def unpublish(gid: int, principal: dict = Depends(_principal)) -> dict:
    user = _require_user(principal)
    return {"game": _call(ugc.unpublish, gid, user["id"])}


@router.post("/api/v1/ugc/games/{gid}/test", summary="沙箱冒烟重跑")
def test_game(gid: int, principal: dict = Depends(_principal)) -> dict:
    user = _require_user(principal)
    game = ugc.get_game(gid)
    if game is None or game["owner_id"] != user["id"]:
        raise HTTPException(404, "游戏不存在")
    return {"smoke": ugc.retest(gid)}


@router.delete("/api/v1/ugc/games/{gid}", summary="删除草稿")
def delete_game(gid: int, principal: dict = Depends(_principal)) -> dict:
    user = _require_user(principal)
    _call(ugc.delete_draft, gid, user["id"])
    return {"deleted": True}
# ------------------------------------------------- 渲染 v2：资源 / 沙箱帧（16）

@router.get("/api/ugc/assets/{slug}/{version}/{path:path}",
            include_in_schema=False)
def get_asset(slug: str, version: str, path: str,
              principal: dict = Depends(_principal)) -> Response:
    """已声明资源的只读服务（公开版本；作者可预览自己的草稿）。"""
    found = ugc.version_row(slug, version)
    if found is None and principal.get("id"):
        found = ugc.version_row(slug, version, statuses=("draft", "pending"))
        if (found is not None and found[0]["owner_id"] != principal["id"]
                and principal.get("role") != "admin"):
            found = None
    if found is None:
        raise HTTPException(404, "资源不存在")
    return ugc_assets.asset_response(found[1], path)


@router.get("/api/ugc/render/{slug}/{version}/frame", include_in_schema=False)
def get_render_frame(slug: str, version: str) -> HTMLResponse:
    """沙箱渲染帧（仅 renderer_enabled 时可用）。"""
    found = ugc.version_row(slug, version)
    if found is None:
        raise HTTPException(404, "渲染器不存在")
    stored = found[1]["meta"]
    meta = stored.get("meta", stored)
    if not (meta.get("renderer") and stored.get("renderer_enabled")):
        raise HTTPException(403, "沙箱渲染器未开启")
    return HTMLResponse(ugc_assets.frame_html(found[1]),
                        headers=ugc_assets.FRAME_HEADERS)


# ---------------------------------------------------------------- admin face

@admin_router.get("", summary="审核队列 / 全部游戏")
def admin_list(status: str | None = Query(None, pattern="^(all)$"),
               principal: dict = Depends(_principal)) -> dict:
    _require_admin(principal)
    if status == "all":
        conn_games = []
        for g in ugc.list_all_games():
            conn_games.append(g)
        return {"games": conn_games}
    return {"games": ugc.review_queue()}


@admin_router.post("/{gid}/approve", summary="审核通过并发布")
def approve(gid: int, principal: dict = Depends(_principal)) -> dict:
    admin = _require_admin(principal)
    return {"game": _call(ugc.approve, gid, admin["id"])}


@admin_router.post("/{gid}/reject", summary="驳回（附意见）")
def reject(gid: int, req: NoteIn, principal: dict = Depends(_principal)) -> dict:
    admin = _require_admin(principal)
    return {"game": _call(ugc.reject, gid, admin["id"], req.note)}


@admin_router.post("/{gid}/ban", summary="下架")
def ban(gid: int, principal: dict = Depends(_principal)) -> dict:
    admin = _require_admin(principal)
    return {"game": _call(ugc.ban, gid, admin["id"])}


@admin_router.post("/{gid}/unban", summary="恢复（回到草稿）")
def unban(gid: int, principal: dict = Depends(_principal)) -> dict:
    admin = _require_admin(principal)
    return {"game": _call(ugc.unban, gid, admin["id"])}


@admin_router.post("/{gid}/pause", summary="暂停（含熔断）")
def pause(gid: int, req: ReasonIn, principal: dict = Depends(_principal)) -> dict:
    _require_admin(principal)
    return {"game": _call(ugc.pause, gid, req.reason)}


@admin_router.post("/{gid}/resume", summary="恢复运行")
def resume(gid: int, principal: dict = Depends(_principal)) -> dict:
    _require_admin(principal)
    return {"game": _call(ugc.resume, gid)}


@admin_router.post("/{gid}/rollback", summary="回滚到历史版本")
def rollback(gid: int, req: RollbackIn, principal: dict = Depends(_principal)) -> dict:
    admin = _require_admin(principal)
    return {"game": _call(ugc.rollback, gid, req.version_id, admin["id"])}


@admin_router.post("/{gid}/retest", summary="沙箱冒烟重跑（审核用）")
def retest(gid: int, principal: dict = Depends(_principal)) -> dict:
    _require_admin(principal)
    return {"smoke": _call(ugc.retest, gid)}


@admin_router.get("/{gid}/renderer", summary="渲染器源码预览（审核用）")
def get_renderer(gid: int, principal: dict = Depends(_principal)) -> dict:
    _require_admin(principal)
    v = ugc.latest_version(gid)
    if v is None:
        raise HTTPException(404, "游戏不存在")
    return ugc_assets.renderer_source(v)


@admin_router.post("/{gid}/renderer", summary="开启/关闭沙箱渲染器")
def set_renderer(gid: int, req: RendererIn,
                 principal: dict = Depends(_principal)) -> dict:
    _require_admin(principal)
    return {"version": _call(ugc.set_renderer_enabled, gid, req.enabled)}

