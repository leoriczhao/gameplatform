"""Model hosting tests: upload/validate/list/delete/eval + model sessions."""
import os
import sys
import tempfile
from pathlib import Path

import numpy as np
import onnx
from onnx import TensorProto, helper

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

_tmp = tempfile.TemporaryDirectory()
os.environ["SCORES_DB"] = str(Path(_tmp.name) / "scores.db")
os.environ["MODELS_DIR"] = str(Path(_tmp.name) / "models")

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402

client = TestClient(main.app)
USER = client.post("/api/v1/auth/register",
                   json={"username": "modeluser1", "password": "password123"}
                   ).json()
H = {"Authorization": f"Bearer {USER['token']}"}


def _make_onnx(in_shape, out_shape, path):
    """Minimal ONNX model: input -> (random affine) -> output."""
    rng = np.random.default_rng(0)
    w = rng.normal(size=(np.prod(out_shape), np.prod(in_shape))).astype(np.float32)
    b = np.zeros(np.prod(out_shape), dtype=np.float32)
    graph = helper.make_graph(
        [helper.make_node("MatMul", ["x", "W"], ["y"]),
         helper.make_node("Add", ["y", "B"], ["out"])],
        "m",
        [helper.make_tensor_value_info("x", TensorProto.FLOAT, list(in_shape))],
        [helper.make_tensor_value_info("out", TensorProto.FLOAT, list(out_shape))],
        [helper.make_tensor("W", TensorProto.FLOAT,
                            [np.prod(out_shape), np.prod(in_shape)], w.tobytes()),
         helper.make_tensor("B", TensorProto.FLOAT, [np.prod(out_shape)], b.tobytes())],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
    onnx.save(model, path)


def _make_onnx(in_shape, out_shape, path):
    """Minimal ONNX model: input -> flatten -> (random affine) -> output."""
    rng = np.random.default_rng(0)
    w = rng.normal(size=(np.prod(in_shape), np.prod(out_shape))).astype(np.float32)
    b = np.zeros(np.prod(out_shape), dtype=np.float32)
    graph = helper.make_graph(
        [helper.make_node("Flatten", ["x"], ["xf"], axis=1),
         helper.make_node("MatMul", ["xf", "W"], ["y"]),
         helper.make_node("Add", ["y", "B"], ["out"])],
        "m",
        [helper.make_tensor_value_info("x", TensorProto.FLOAT, list(in_shape))],
        [helper.make_tensor_value_info("out", TensorProto.FLOAT, list(out_shape))],
        [helper.make_tensor("W", TensorProto.FLOAT,
                            [np.prod(in_shape), np.prod(out_shape)],
                            w.tobytes(), raw=True),
         helper.make_tensor("B", TensorProto.FLOAT, [np.prod(out_shape)],
                            b.tobytes(), raw=True)],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
    onnx.save(model, path)


def _upload(game, name, in_shape, out_shape):
    path = Path(_tmp.name) / f"{game}-{name}.onnx"
    _make_onnx(in_shape, out_shape, path)
    with open(path, "rb") as f:
        r = client.post("/api/v1/models",
                        files={"file": (path.name, f, "application/octet-stream")},
                        data={"game": game, "name": name}, headers=H)
    return r


def test_upload_and_list_snake():
    r = _upload("snake", "测试DQN", (1, 1334), (1, 3))
    assert r.status_code == 200, r.text
    model = r.json()["model"]
    assert model["game"] == "snake" and model["io_contract"] == "game.snake"
    assert model["status"] == "active"
    r = client.get("/api/v1/models", headers=H)
    assert [m["name"] for m in r.json()["models"]] == ["测试DQN"]


def test_upload_wrong_shape_rejected():
    r = _upload("snake", "坏模型", (1, 100), (1, 3))
    assert r.status_code == 400
    assert "shape" in r.json()["detail"]


def test_upload_requires_login():
    path = Path(_tmp.name) / "anon.onnx"
    _make_onnx((1, 1334), (1, 3), path)
    with open(path, "rb") as f:
        r = client.post("/api/v1/models",
                        files={"file": (path.name, f, "application/octet-stream")},
                        data={"game": "snake", "name": "匿名"})
    assert r.status_code == 401


def test_eval_snake_model():
    r = _upload("snake", "评估用", (1, 1334), (1, 3))
    model_id = r.json()["model"]["id"]
    r = client.post(f"/api/v1/models/{model_id}/eval", headers=H)
    assert r.status_code == 200, r.text
    m = r.json()["metrics"]
    assert m["games"] == 3 and "avg_score" in m and "avg_length" in m
    # eval metrics must persist in meta (06 U08 closed-loop criterion)
    r = client.get(f"/api/v1/models/{model_id}", headers=H)
    assert r.status_code == 200, r.text
    assert r.json()["model"]["meta"]["eval"]["games"] == 3


def test_delete_model():
    r = _upload("tetris", "待删除", (1, 2, 20, 10), (1, 4))
    assert r.status_code == 200, r.text
    mid = r.json()["model"]["id"]
    r = client.delete(f"/api/v1/models/{mid}", headers=H)
    assert r.status_code == 200
    r = client.get("/api/v1/models", headers=H)
    assert all(m["id"] != mid for m in r.json()["models"])


def test_microrts_session_vs_uploaded_model():
    r = _upload("microrts", "对手模型", (1, 1546), (1, 140))
    assert r.status_code == 200, r.text
    mid = r.json()["model"]["id"]
    r = client.post("/api/v1/microrts/play/sessions",
                    json={"seed": 9, "opponent": {"type": "model", "model_id": mid}},
                    headers=H)
    assert r.status_code == 200, r.text
    s = r.json()["session"]
    sid = s["id"]
    base0 = s["state"]["units"][0]["id"]
    for _ in range(3):
        r = client.post(f"/api/v1/microrts/play/sessions/{sid}/actions",
                        json={"actions": [[base0, 5, 1, "worker"]]}, headers=H)
        assert r.status_code == 200, r.text
    assert r.json()["tick"] == 3
    client.post(f"/api/v1/microrts/play/sessions/{sid}/leave", headers=H)


def test_model_autopilot_session():
    r = _upload("tetris", "代打模型", (1, 2, 20, 10), (1, 4))
    assert r.status_code == 200, r.text
    mid = r.json()["model"]["id"]
    r = client.post("/api/v1/tetris/play/sessions",
                    json={"controller": {"type": "model", "model_id": mid}},
                    headers=H)
    assert r.status_code == 200, r.text
    sid = r.json()["session"]["id"]
    # actions: null -> server runs the model. Tetris ticks only advance on
    # hard drop (action 3), so the random model may need several autopilot
    # steps before one lands on a hard drop — keep submitting until tick
    # advances (bounded, deterministic given the seeded model).
    tick = 0
    for _ in range(10):
        r = client.post(f"/api/v1/tetris/play/sessions/{sid}/actions",
                        json={"actions": None}, headers=H)
        assert r.status_code == 200, r.text
        tick = r.json()["tick"]
        if tick >= 1:
            break
    assert tick >= 1
    client.post(f"/api/v1/tetris/play/sessions/{sid}/leave", headers=H)
