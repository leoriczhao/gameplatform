"""PvP session + match + rating tests (人 vs 人 and 模型 vs 模型)."""
import os
import sys
import tempfile
import time
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
import sessions  # noqa: E402

# sessions may already be imported by other test modules with defaults;
# patch the module attributes directly for fast timeout tests
sessions.PVP_TIMEOUT = 1.0
sessions.PVP_MAX_TIMEOUTS = 2

client = TestClient(main.app)


def _user(name):
    r = client.post("/api/v1/auth/register",
                    json={"username": name, "password": "password123"})
    assert r.status_code == 200, r.text
    return r.json()


A = _user("pvpa")
B = _user("pvpb")
HA = {"Authorization": f"Bearer {A['token']}"}
HB = {"Authorization": f"Bearer {B['token']}"}


def test_pvp_requires_login():
    r = client.post("/api/v1/microrts/play/sessions", json={"kind": "pvp"})
    assert r.status_code == 401


def test_pvp_create_join_and_steps():
    r = client.post("/api/v1/microrts/play/sessions",
                    json={"kind": "pvp"}, headers=HA)
    assert r.status_code == 200, r.text
    invite = r.json()["invite"]
    sid = r.json()["session"]["id"]
    assert r.json()["session"]["status"] == "waiting"

    # B joins via invite
    r = client.post("/api/v1/microrts/play/sessions",
                    json={"kind": "pvp", "invite": invite, "side": "p1"}, headers=HB)
    assert r.status_code == 200, r.text
    assert r.json()["session"]["status"] == "active"
    assert r.json()["session"]["p1_joined"] is True

    # A submits -> waiting for p1
    r = client.post(f"/api/v1/microrts/play/sessions/{sid}/actions",
                    json={"actions": []}, headers=HA)
    assert r.status_code == 200, r.text
    assert r.json()["advanced"] is False and r.json()["waiting_for"] == "p1"

    # B submits -> both in, one tick advances
    r = client.post(f"/api/v1/microrts/play/sessions/{sid}/actions",
                    json={"actions": []}, headers=HB)
    assert r.status_code == 200, r.text
    assert r.json()["advanced"] is True and r.json()["tick"] == 1

    # non-player is rejected
    C = _user("pvpc")
    r = client.post(f"/api/v1/microrts/play/sessions/{sid}/actions",
                    json={"actions": []},
                    headers={"Authorization": f"Bearer {C['token']}"})
    assert r.status_code == 403


def test_pvp_resign_records_match_and_ratings():
    r = client.post("/api/v1/microrts/play/sessions",
                    json={"kind": "pvp"}, headers=HA)
    invite = r.json()["invite"]
    sid = r.json()["session"]["id"]
    client.post("/api/v1/microrts/play/sessions",
                json={"kind": "pvp", "invite": invite, "side": "p1"}, headers=HB)
    # A resigns -> B wins
    r = client.post(f"/api/v1/microrts/play/sessions/{sid}/leave", headers=HA)
    assert r.status_code == 200
    assert r.json()["winner"] == 1

    # match recorded for A
    r = client.get("/api/v1/matches", headers=HA)
    matches = r.json()["matches"]
    assert any(m["kind"] == "pvp" and m["status"] == "finished" and
               m["result"]["winner"] == 1 and m["result"]["cause"] == "resigned"
               for m in matches)

    # ratings updated (B up, A down from 1200)
    r = client.get("/api/v1/ratings/microrts", headers=HA)
    items = {i["name"]: i["rating"] for i in r.json()["items"]}
    assert items.get("pvpb", 1200) > 1200
    assert items.get("pvpa", 1200) < 1200


def test_pvp_timeout_auto_waits():
    r = client.post("/api/v1/microrts/play/sessions",
                    json={"kind": "pvp"}, headers=HA)
    invite = r.json()["invite"]
    sid = r.json()["session"]["id"]
    client.post("/api/v1/microrts/play/sessions",
                json={"kind": "pvp", "invite": invite, "side": "p1"}, headers=HB)
    client.post(f"/api/v1/microrts/play/sessions/{sid}/actions",
                json={"actions": []}, headers=HA)
    time.sleep(1.2)  # PVP_TIMEOUT=1s
    # a poll (GET) substitutes B's missing commands and advances the tick
    r = client.get(f"/api/v1/microrts/play/sessions/{sid}", headers=HB)
    assert r.json()["session"]["state"]["tick"] == 1
    # B submits late -> it counts for the NEXT tick (A still has to submit)
    r = client.post(f"/api/v1/microrts/play/sessions/{sid}/actions",
                    json={"actions": []}, headers=HB)
    assert r.json()["advanced"] is False
    assert r.json()["waiting_for"] == "p0"
    # A submits again -> the game keeps flowing
    r = client.post(f"/api/v1/microrts/play/sessions/{sid}/actions",
                    json={"actions": []}, headers=HA)
    assert r.json()["advanced"] is True
    assert r.json()["tick"] == 2


def test_pvp_submitted_indicator():
    r = client.post("/api/v1/microrts/play/sessions",
                    json={"kind": "pvp"}, headers=HA)
    invite = r.json()["invite"]
    sid = r.json()["session"]["id"]
    client.post("/api/v1/microrts/play/sessions",
                json={"kind": "pvp", "invite": invite, "side": "p1"}, headers=HB)
    client.post(f"/api/v1/microrts/play/sessions/{sid}/actions",
                json={"actions": []}, headers=HB)
    r = client.get(f"/api/v1/microrts/play/sessions/{sid}", headers=HA)
    players = {p["side"]: p for p in r.json()["session"]["players"]}
    assert players["p1"]["submitted"] is True
    assert players["p0"]["submitted"] is False


def test_pvp_waiting_room_can_be_cancelled():
    r = client.post("/api/v1/microrts/play/sessions",
                    json={"kind": "pvp"}, headers=HA)
    sid = r.json()["session"]["id"]
    r = client.post(f"/api/v1/microrts/play/sessions/{sid}/leave", headers=HA)
    assert r.status_code == 200
    r = client.get(f"/api/v1/microrts/play/sessions/{sid}", headers=HA)
    assert r.json()["session"]["status"] == "cancelled"


def test_pvp_timeout_forfeit_records_match():
    r = client.post("/api/v1/microrts/play/sessions",
                    json={"kind": "pvp"}, headers=HA)
    invite = r.json()["invite"]
    sid = r.json()["session"]["id"]
    client.post("/api/v1/microrts/play/sessions",
                json={"kind": "pvp", "invite": invite, "side": "p1"}, headers=HB)
    client.post(f"/api/v1/microrts/play/sessions/{sid}/actions",
                json={"actions": []}, headers=HA)
    time.sleep(1.2)  # auto-wait #1 -> tick advances with B empty
    client.post(f"/api/v1/microrts/play/sessions/{sid}/actions",
                json={"actions": []}, headers=HA)
    time.sleep(1.2)  # auto-wait #2 -> B forfeits (PVP_MAX_TIMEOUTS=2)
    r = client.get(f"/api/v1/microrts/play/sessions/{sid}", headers=HA)
    s = r.json()["session"]
    assert s["status"] == "finished"
    assert s["winner"] == 0 and s["cause"] == "timeout"

    # the poll-driven finish is recorded as a match with ratings
    r = client.get("/api/v1/matches", headers=HA)
    assert any(m["kind"] == "pvp" and m["status"] == "finished"
               and m["result"]["cause"] == "timeout" for m in r.json()["matches"])


def _microrts_model(name, user_headers):
    rng = np.random.default_rng(42)
    w = rng.normal(size=(1546, 140)).astype(np.float32)
    b = np.zeros(140, dtype=np.float32)
    g = helper.make_graph(
        [helper.make_node("Flatten", ["x"], ["xf"], axis=1),
         helper.make_node("MatMul", ["xf", "W"], ["y"]),
         helper.make_node("Add", ["y", "B"], ["out"])], "m",
        [helper.make_tensor_value_info("x", TensorProto.FLOAT, [1, 1546])],
        [helper.make_tensor_value_info("out", TensorProto.FLOAT, [1, 140])],
        [helper.make_tensor("W", TensorProto.FLOAT, [1546, 140], w.tobytes(), raw=True),
         helper.make_tensor("B", TensorProto.FLOAT, [140], b.tobytes(), raw=True)])
    path = Path(_tmp.name) / f"{name}.onnx"
    onnx.save(helper.make_model(g, opset_imports=[helper.make_opsetid("", 13)]), path)
    with open(path, "rb") as f:
        r = client.post("/api/v1/models",
                        files={"file": (path.name, f, "application/octet-stream")},
                        data={"game": "microrts", "name": name}, headers=user_headers)
    assert r.status_code == 200, r.text
    return r.json()["model"]["id"]


def test_model_vs_model_match():
    mid_a = _microrts_model("对战模型A", HA)
    mid_b = _microrts_model("对战模型B", HB)
    r = client.post("/api/v1/matches",
                    json={"game": "microrts", "model_a": mid_a, "model_b": mid_b},
                    headers=HA)
    assert r.status_code == 200, r.text
    match_id = r.json()["match_id"]

    # poll the async worker until finished
    status = None
    for _ in range(100):
        r = client.get(f"/api/v1/matches/{match_id}", headers=HA)
        m = r.json()["match"]
        status = m["status"]
        if status in ("finished", "failed"):
            break
        time.sleep(0.1)
    assert status == "finished", m
    assert m["result"]["tick"] > 0
    assert m["replay"] and len(m["replay"]) > 0


def test_model_vs_builtin_ai():
    mid = _microrts_model("打AI模型", HA)
    r = client.post("/api/v1/matches",
                    json={"game": "microrts", "model_a": mid,
                          "model_b": "ai:worker_rush"}, headers=HA)
    assert r.status_code == 200, r.text
    match_id = r.json()["match_id"]
    for _ in range(100):
        m = client.get(f"/api/v1/matches/{match_id}", headers=HA).json()["match"]
        if m["status"] in ("finished", "failed"):
            break
        time.sleep(0.1)
    assert m["status"] == "finished"
