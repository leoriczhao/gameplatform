"""Model hosting API: /api/v1/models/* — see docs/design/04."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

import models
import inference
from auth_routes import _principal

router = APIRouter(tags=["models"], prefix="/api/v1/models")


def _require_user(principal: dict) -> dict:
    if principal.get("role") == "guest" or not principal.get("id"):
        raise HTTPException(401, "请先登录（注册后即可上传模型）")
    return principal


@router.post("", summary="上传 ONNX 模型")
async def upload(file: UploadFile = File(...),
                 game: str = Form(...),
                 name: str = Form(...),
                 principal: dict = Depends(_principal)) -> dict:
    user = _require_user(principal)
    data = await file.read()
    try:
        model = models.create_model(user["id"], game, name, data,
                                    file.filename or "model.onnx")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"model": model}


@router.get("", summary="我的模型列表")
def my_models(principal: dict = Depends(_principal)) -> dict:
    user = _require_user(principal)
    return {"models": models.list_models(user["id"])}


@router.get("/{model_id}", summary="模型详情")
def get(model_id: int, principal: dict = Depends(_principal)) -> dict:
    model = models.get_model(model_id)
    if model is None or model["status"] != "active":
        raise HTTPException(404, "model not found")
    return {"model": model}


@router.delete("/{model_id}", summary="删除模型")
def delete(model_id: int, principal: dict = Depends(_principal)) -> dict:
    user = _require_user(principal)
    if not models.delete_model(model_id, user["id"]):
        raise HTTPException(404, "model not found")
    return {"status": "deleted"}


@router.post("/{model_id}/eval", summary="标准评估（N 局，结果写回 meta）")
def evaluate(model_id: int, principal: dict = Depends(_principal)) -> dict:
    user = _require_user(principal)
    model = models.get_model(model_id)
    if model is None or model["status"] != "active":
        raise HTTPException(404, "model not found")
    if model["owner_id"] != user["id"]:
        raise HTTPException(403, "只能评估自己的模型")
    try:
        metrics = models.evaluate(model)
    except inference.ModelError as e:
        raise HTTPException(500, str(e))
    return {"model_id": model_id, "metrics": metrics}
