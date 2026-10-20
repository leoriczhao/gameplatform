"""Seed game loader tests (13 G1): official packages go through the same
pipeline as uploads but auto-publish; idempotent by slug, version upgrades swap."""
import io
import os
import sys
import tempfile
import zipfile
from pathlib import Path

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
import ugc  # noqa: E402
from openenv_helpers import ws_reset, ws_step  # noqa: E402

client = TestClient(main.app)

GOOD_YAML = """slug: seed-counter
title: 种子计数器
description: seed 测试
version: {version}
board:
  width: 4
  height: 4
  palette:
    empty: {{ glyph: "·" }}
    full:  {{ glyph: "■" }}
"""

COUNTER_CODE = '''
class Counter:
    score_bounds = (0, 100)
    def info(self):
        return {"grid": [4, 4], "action_space": "0-1"}
    def new_state(self, seed, options=None):
        return {"tick": 0, "done": False, "winner": None, "cause": None,
                "n": 0, "board": [["empty"] * 4 for _ in range(4)]}
    def validate_state(self, state):
        if state["board"][0][0] not in ("empty", "full"):
            raise ValueError("bad cell")
    def validate_action(self, action, state):
        if not isinstance(action, int):
            raise ValueError("int required")
    def step_state(self, state, action):
        if state.get("done"):
            return state
        s = dict(state, n=state["n"] + 1, tick=state["tick"] + 1)
        s["board"] = [row[:] for row in state["board"]]
        s["board"][0][0] = "full" if s["n"] >= 10 else "empty"
        if s["n"] >= 10:
            s.update(done=True, winner=0, cause="done")
        return s
    def sample_action(self, state):
        return 1
def get_adapter():
    return Counter()
'''


def _pack(version="1.0.0") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("game.yaml", GOOD_YAML.format(version=version))
        zf.writestr("__init__.py", COUNTER_CODE)
        zf.writestr("README.md", "# seed")
    return buf.getvalue()


@pytest.fixture
def admin_id(monkeypatch):
    monkeypatch.setenv("ADMIN_USERNAME", "seedadmin")
    monkeypatch.setenv("ADMIN_PASSWORD", "adminsecret1")
    admin_store.bootstrap_admin()
    r = client.post("/api/v1/auth/login",
                    json={"username": "seedadmin", "password": "adminsecret1"})
    return r.json()["user"]["id"]


def test_seed_publish_register_and_play(admin_id):
    g, v = ugc.seed_game(admin_id, _pack())
    assert g["status"] == "published" and g["slug"] == "seed-counter"
    assert v["status"] == "active"
    ugc.load_published_into_registry()
    assert "seed-counter" in registry.GAMES
    with client.websocket_connect("/api/openenv/seed-counter/ws") as ws:
        result = ws_reset(ws, seed=1, obs_mode="state")
        assert len(result["observation"]["state"]["board"]) == 4
        assert ws_step(ws, 1)["observation"]["state"]["tick"] == 1


def test_seed_idempotent_same_version(admin_id):
    g1, v1 = ugc.seed_game(admin_id, _pack("1.0.0"))
    g2, v2 = ugc.seed_game(admin_id, _pack("1.0.0"))   # same version -> skip
    assert g2["id"] == g1["id"]
    assert v2["id"] == v1["id"]
    conn = ugc._db()
    try:
        n = conn.execute(
            "SELECT COUNT(*) FROM ugc_versions WHERE game_id=?", (g1["id"],)).fetchone()[0]
    finally:
        conn.close()
    assert n == 1


def test_seed_version_upgrade_swaps(admin_id):
    g1, v1 = ugc.seed_game(admin_id, _pack("1.0.0"))
    g2, v2 = ugc.seed_game(admin_id, _pack("1.1.0"))
    assert g2["id"] == g1["id"]
    assert v2["version"] == "1.1.0" and v2["status"] == "active"
    old = ugc._db().execute("SELECT status FROM ugc_versions WHERE id=?",
                            (v1["id"],)).fetchone()[0]
    ugc._db().close()
    assert old == "superseded"
    # 低版本再播种被拒
    with pytest.raises(ValueError, match="递增"):
        ugc.seed_game(admin_id, _pack("1.0.1"))


def test_seed_slug_conflicts_with_user_upload(admin_id):
    ugc.seed_game(admin_id, _pack("2.0.0"))
    ugc.load_published_into_registry()
    # 用户上传同名 slug：校验器按已注册 slug 拒绝（同一条管线）
    from auth_routes import _principal  # noqa: F401
    r = client.post("/api/v1/auth/register",
                    json={"username": "seeduser", "password": "password123"})
    h = {"Authorization": "Bearer " + r.json()["token"]}
    r2 = client.post("/api/v1/ugc/games",
                     files={"file": ("x.zip", _pack(), "application/zip")},
                     data={"changelog": "x"}, headers=h)
    assert r2.status_code == 400 and "占用" in r2.text
