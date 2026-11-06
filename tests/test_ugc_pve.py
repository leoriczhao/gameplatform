"""PvE match recording (11 P4): a finished v2 practice match persists as a
kind=pve record and its sealed frames are readable through the v2 stage API.
(The v1 play-session and public replay endpoints were removed in M4.)"""
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
import ugc_runner  # noqa: E402

client = TestClient(main.app)


@pytest.fixture(autouse=True)
def _restore_registry():
    """Published test games never leak into other test modules."""
    before = set(registry.GAMES)
    yield
    for slug in set(registry.GAMES) - before:
        registry.unregister(slug)
        ugc_runner.drop_worker(slug)

GOOD_YAML = """slug: pve-counter
title: PvE 计数器
description: PvE 落库测试
version: 1.0.0
board:
  width: 4
  height: 4
  palette:
    empty: { glyph: "·" }
    full:  { glyph: "■" }
"""

COUNTER_CODE = '''
class Counter:
    score_bounds = (0, 100)
    def info(self):
        return {"grid": [4, 4], "action_space": "0-1"}
    def new_state(self, seed, options=None):
        return {"tick": 0, "done": False, "winner": None, "cause": None,
                "n": 0, "seed": int(seed), "score": 0,
                "board": [["empty"] * 4 for _ in range(4)]}
    def validate_state(self, state):
        if state["board"][0][0] not in ("empty", "full"):
            raise ValueError("bad cell")
    def validate_action(self, action, state):
        if not isinstance(action, int):
            raise ValueError("int required")
    def step_state(self, state, action):
        if state.get("done"):
            return state
        s = dict(state, n=state["n"] + 1, tick=state["tick"] + 1,
                 score=state["score"] + 10)
        s["board"] = [row[:] for row in state["board"]]
        s["board"][0][0] = "full" if s["n"] >= 3 else "empty"
        if s["n"] >= 3:
            s.update(done=True, winner=0, cause="done")
        return s
    def sample_action(self, state):
        return 1
def get_adapter():
    return Counter()
'''


def _user(name):
    r = client.post("/api/v1/auth/register",
                    json={"username": name, "password": "password123"})
    assert r.status_code == 200, r.text
    return r.json()


def _h(u):
    return {"Authorization": f"Bearer {u['token']}"}


@pytest.fixture
def admin(monkeypatch):
    monkeypatch.setenv("ADMIN_USERNAME", "ugcpveadmin")
    monkeypatch.setenv("ADMIN_PASSWORD", "adminsecretpve")
    admin_store.bootstrap_admin()
    r = client.post("/api/v1/auth/login",
                    json={"username": "ugcpveadmin",
                          "password": "adminsecretpve"})
    assert r.status_code == 200, r.text
    return r.json()


def _publish(admin, author):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("game.yaml", GOOD_YAML)
        zf.writestr("__init__.py", COUNTER_CODE)
        zf.writestr("README.md", "# pve")
    r = client.post("/api/v1/ugc/games",
                    files={"file": ("pve-counter.zip", buf.getvalue(),
                                    "application/zip")},
                    data={"changelog": "init"}, headers=_h(author))
    assert r.status_code == 200, r.text
    gid = client.get("/api/v1/ugc/games", headers=_h(author)).json()["games"][0]["id"]
    client.post(f"/api/v1/ugc/games/{gid}/submit", headers=_h(author))
    assert client.post(f"/api/v1/admin/ugc/{gid}/approve",
                       headers=_h(admin)).status_code == 200


def test_pve_finish_records_match_and_seals_frames(admin):
    A = _user("ugcpve1")
    _publish(admin, A)
    # 开一局 v2 练习局（选定 seed -> 不入榜），走 3 步到 done
    r = client.post("/api/v2/matches", headers=_h(A),
                    json={"game": "pve-counter", "settings": {"seed": 7}})
    assert r.status_code == 201, r.text
    uid, tick = r.json()["id"], 0
    for _ in range(3):
        r = client.post(f"/api/v2/matches/{uid}/actions", headers=_h(A),
                        json={"tick": tick, "action": 1})
        assert r.status_code == 202, r.text
        tick += 1
    view = client.get(f"/api/v2/matches/{uid}", headers=_h(A)).json()
    assert view["status"] == "finished"
    # 落库：我的对局里出现一条 pve，且封存帧可读（seed + 每步动作）
    mine = client.get("/api/v1/matches", headers=_h(A)).json()["matches"]
    row = next(m for m in mine if m.get("uid") == uid)
    assert row["kind"] == "pve" and row["game"] == "pve-counter"
    assert row["status"] == "finished" and row["result"]["cause"] == "done"
    frames = client.get(f"/api/v2/matches/{uid}/frames", headers=_h(A)).json()
    assert frames["total"] == 4
    assert frames["frames"][0]["frame"]["seed"] == 7
    assert [f["actions"] for f in frames["frames"][1:]] == [{"p0": 1}] * 3
