"""UGC model contract (11 P5): a published game with meta.contract
accepts ONNX uploads (shape-validated) and evaluates in the sandbox."""
import io
import os
import sys
import tempfile
import zipfile
from pathlib import Path

import numpy as np
import onnx
from onnx import TensorProto, helper
import pytest

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

_tmp = tempfile.TemporaryDirectory()
os.environ["SCORES_DB"] = str(Path(_tmp.name) / "scores.db")
os.environ["MODELS_DIR"] = str(Path(_tmp.name) / "models")

from fastapi.testclient import TestClient  # noqa: E402

import admin as admin_store  # noqa: E402
import main  # noqa: E402
import registry  # noqa: E402

client = TestClient(main.app)

GOOD_YAML = """slug: lin
title: 线性游戏
description: 模型契约测试
version: 1.0.0
board:
  width: 4
  height: 4
  palette:
    empty: { glyph: "·" }
contract:
  in_shape: [1, 4]
  out_shape: [1, 2]
"""

LIN_CODE = '''
class Lin:
    score_bounds = (0, 100)
    def info(self):
        return {"grid": [4, 4], "action_space": "0-1",
                "obs_modes": ["flat"], "obs_shape": [4]}
    def new_state(self, seed, options=None):
        return {"tick": 0, "done": False, "winner": None, "cause": None,
                "n": 0, "seed": int(seed),
                "board": [["empty"] * 4 for _ in range(4)]}
    def validate_state(self, state):
        if len(state["board"]) != 4:
            raise ValueError("bad board")
    def validate_action(self, action, state):
        if not isinstance(action, int) or action not in (0, 1):
            raise ValueError("bad action")
    def step_state(self, state, action):
        if state.get("done"):
            return state
        s = dict(state, n=state["n"] + 1, tick=state["tick"] + 1)
        s["board"] = [row[:] for row in state["board"]]
        if s["n"] >= 5:
            s.update(done=True, winner=0, cause="done")
        return s
    def sample_action(self, state):
        return state["tick"] % 2
    def obs(self, state, mode=None):
        return [float(state["tick"] % 4), float(state["n"] % 4), 0.0, 1.0]
def get_adapter():
    return Lin()
'''


def _user(name):
    r = client.post("/api/v1/auth/register",
                    json={"username": name, "password": "password123"})
    assert r.status_code == 200, r.text
    return r.json()


def _h(u):
    return {"Authorization": f"Bearer {u['token']}"}


def _make_onnx(in_shape, out_shape, path):
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


@pytest.fixture
def admin(monkeypatch):
    monkeypatch.setenv("ADMIN_USERNAME", "ugcmodeladmin")
    monkeypatch.setenv("ADMIN_PASSWORD", "adminsecretm")
    admin_store.bootstrap_admin()
    r = client.post("/api/v1/auth/login",
                    json={"username": "ugcmodeladmin",
                          "password": "adminsecretm"})
    assert r.status_code == 200, r.text
    return r.json()


def _publish(admin, author, slug="lin"):
    buf = io.BytesIO()
    yaml = GOOD_YAML.replace("slug: lin", f"slug: {slug}")
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("game.yaml", yaml)
        zf.writestr("__init__.py", LIN_CODE)
        zf.writestr("README.md", "# " + slug)
    r = client.post("/api/v1/ugc/games",
                    files={"file": (slug + ".zip", buf.getvalue(), "application/zip")},
                    data={"changelog": "init"}, headers=_h(author))
    assert r.status_code == 200, r.text
    gid = client.get("/api/v1/ugc/games", headers=_h(author)).json()["games"][0]["id"]
    client.post(f"/api/v1/ugc/games/{gid}/submit", headers=_h(author))
    assert client.post(f"/api/v1/admin/ugc/{gid}/approve",
                       headers=_h(admin)).status_code == 200
    return gid


def test_ugc_model_upload_and_eval(admin):
    A = _user("ugcmodel1")
    _publish(admin, A)
    assert registry.GAMES["lin"].meta.get("contract")

    # upload a model matching the contract (1,4)->(1,2)
    path = Path(_tmp.name) / "lin.onnx"
    _make_onnx((1, 4), (1, 2), path)
    with open(path, "rb") as f:
        r = client.post("/api/v1/models",
                        files={"file": (path.name, f, "application/octet-stream")},
                        data={"game": "lin", "name": "线性DQN"}, headers=_h(A))
    assert r.status_code == 200, r.text
    model = r.json()["model"]
    assert model["io_contract"] == "game.lin"   # 13 G3：契约命名统一 game.<slug>

    # wrong shape rejected
    path2 = Path(_tmp.name) / "lin-bad.onnx"
    _make_onnx((1, 8), (1, 2), path2)
    with open(path2, "rb") as f:
        r = client.post("/api/v1/models",
                        files={"file": (path2.name, f, "application/octet-stream")},
                        data={"game": "lin", "name": "坏模型"}, headers=_h(A))
    assert r.status_code == 400 and "shape" in r.text

    # eval runs 3 games in the sandbox via the generic contract
    r = client.post(f"/api/v1/models/{model['id']}/eval", headers=_h(A))
    assert r.status_code == 200, r.text
    m = r.json()["metrics"]
    assert m["games"] == 3 and "avg_length" in m


def test_report_ugc_target_types(admin):
    A = _user("ugcmodel3")
    gid = _publish(admin, A, slug="lin-report")
    r = client.post("/api/v1/reports",
                    json={"target_type": "ugc_game", "target_id": gid,
                          "reason": "含违规内容"}, headers=_h(A))
    assert r.status_code == 200, r.text
    assert r.json()["report"]["target_type"] == "ugc_game"


def test_no_contract_game_rejects_model():
    A = _user("ugcmodel2")
    # guess-number has no contract -> upload rejected
    r = client.post("/api/v1/models",
                    files={"file": ("x.onnx", b"not-onnx", "application/octet-stream")},
                    data={"game": "guess-number", "name": "x"}, headers=_h(A))
    # (guess-number isn't published in this test process; supports_models is False)
    assert r.status_code == 400
