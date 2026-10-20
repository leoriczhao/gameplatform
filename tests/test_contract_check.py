"""A1: game.yaml contract.* must agree with the runtime info().schemas."""
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
import contract_check  # noqa: E402
import main  # noqa: E402
import registry  # noqa: E402

client = TestClient(main.app)


def _info(obs_modes=("flat",), observations=None, action=None):
    # 完整 schemas（含 state）会被 _environment_schemas 原样采用
    return {"obs_modes": list(obs_modes),
            "schemas": {
                "state": {"type": "object"},
                "observations": observations or {"flat": {"x-shape": [4]}},
                "action": action or {}}}


# ------------------------------------------------------------------ unit


def test_official_packages_pass_their_own_contract():
    for slug in ("snake", "tetris", "microrts"):
        adapter = registry.GAMES[slug]
        contract_check.validate_contract(adapter.meta, adapter.info())


def test_no_contract_is_ignored():
    contract_check.validate_contract({}, {"obs_modes": []})
    contract_check.validate_contract({"contract": {}}, {"obs_modes": []})


def test_obs_mode_must_be_declared_by_the_package():
    meta = {"contract": {"in_shape": [1, 4], "obs_mode": "rotwin"}}
    with pytest.raises(ValueError, match="obs_mode"):
        contract_check.validate_contract(meta, _info())


def test_in_shape_must_match_the_observation_schema():
    meta = {"contract": {"in_shape": [1, 8], "obs_mode": "flat"}}
    with pytest.raises(ValueError, match="in_shape"):
        contract_check.validate_contract(meta, _info())


def test_in_shape_without_obs_mode_is_allowed():
    # composite games (microrts): the model input is not an observation mode
    meta = {"contract": {"in_shape": [1, 1546], "out_shape": [1, 140],
                         "protocol": "composite"}}
    contract_check.validate_contract(meta, _info())


def test_simple_out_shape_must_match_the_action_count():
    meta = {"contract": {"in_shape": [1, 4], "out_shape": [1, 5],
                         "protocol": "simple"}}
    with pytest.raises(ValueError, match="out_shape"):
        contract_check.validate_contract(
            meta, _info(action={"enum": [0, 1, 2, 3]}))


def test_bad_protocol_and_shapes_are_rejected():
    with pytest.raises(ValueError, match="protocol"):
        contract_check.validate_contract(
            {"contract": {"protocol": "weird"}}, _info())
    with pytest.raises(ValueError, match="in_shape"):
        contract_check.validate_contract(
            {"contract": {"in_shape": []}}, _info())
    with pytest.raises(ValueError, match="out_shape"):
        contract_check.validate_contract(
            {"contract": {"out_shape": [1, 0]}}, _info())


# ---------------------------------------------------------- integration

DRIFT_YAML = """slug: drift
title: 契约漂移
description: A1 校验用
version: 1.0.0
board:
  width: 4
  height: 4
  palette:
    empty: { glyph: "·" }
contract:
  in_shape: [1, 8]
  out_shape: [1, 2]
  obs_mode: flat
"""

DRIFT_CODE = '''
class Drift:
    score_bounds = (0, 100)
    def info(self):
        return {"grid": [4, 4], "action_space": "0-1",
                "obs_modes": ["flat"], "obs_shape": [4]}
    def new_state(self, seed, options=None):
        return {"tick": 0, "done": False, "winner": None, "cause": None,
                "board": [["empty"] * 4 for _ in range(4)]}
    def validate_state(self, state):
        if len(state["board"]) != 4:
            raise ValueError("bad board")
    def validate_action(self, action, state):
        if not isinstance(action, int):
            raise ValueError("int required")
    def step_state(self, state, action):
        return dict(state, tick=state["tick"] + 1)
    def sample_action(self, state):
        return 0
def get_adapter():
    return Drift()
'''


@pytest.fixture
def admin(monkeypatch):
    monkeypatch.setenv("ADMIN_USERNAME", "contractadmin")
    monkeypatch.setenv("ADMIN_PASSWORD", "adminsecretc")
    admin_store.bootstrap_admin()
    r = client.post("/api/v1/auth/login",
                    json={"username": "contractadmin",
                          "password": "adminsecretc"})
    assert r.status_code == 200, r.text
    return r.json()


def _h(user):
    return {"Authorization": f"Bearer {user['token']}"}


def test_contract_drift_is_rejected_at_approve(admin):
    author = client.post("/api/v1/auth/register",
                         json={"username": "driftauthor",
                               "password": "password123"}).json()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("game.yaml", DRIFT_YAML)
        zf.writestr("__init__.py", DRIFT_CODE)
    r = client.post("/api/v1/ugc/games",
                    files={"file": ("drift.zip", buf.getvalue(),
                                    "application/zip")},
                    data={"changelog": "init"}, headers=_h(author))
    assert r.status_code == 200, r.text
    gid = client.get("/api/v1/ugc/games",
                     headers=_h(author)).json()["games"][0]["id"]
    assert client.post(f"/api/v1/ugc/games/{gid}/submit",
                       headers=_h(author)).status_code == 200
    r = client.post(f"/api/v1/admin/ugc/{gid}/approve", headers=_h(admin))
    assert r.status_code == 400, r.text
    assert "in_shape" in r.text
    assert "drift" not in registry.GAMES  # 校验失败不注册、不发布
