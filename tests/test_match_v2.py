"""Match API v2 (design 17 M1): one Match object for practice, autopilot,
rooms, matchmaking, model matches; deadlines, settlement, records, frames."""
import os
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import onnx
import pytest
from onnx import TensorProto, helper

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
_tmp = tempfile.TemporaryDirectory()
os.environ["SCORES_DB"] = str(Path(_tmp.name) / "scores.db")
os.environ["MODELS_DIR"] = str(Path(_tmp.name) / "models")

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
import match_engine as engine  # noqa: E402
import matches as store  # noqa: E402
import registry  # noqa: E402

client = TestClient(main.app)
_N = iter(range(10_000))


def _user(prefix="mv2"):
    name = f"{prefix}{next(_N)}{os.getpid() % 1000}"
    r = client.post("/api/v1/auth/register", json={"username": name, "password": "password123"})
    assert r.status_code == 200, r.text
    u = r.json()
    u["h"] = {"Authorization": f"Bearer {u['token']}"}
    return u


def _create(u, **body):
    r = client.post("/api/v2/matches", json=body, headers=u["h"])
    assert r.status_code == 201, r.text
    return r.json()


def _act(u, mid, tick, action):
    return client.post(f"/api/v2/matches/{mid}/actions", json={"tick": tick, "action": action},
                       headers=u["h"])


def _view(u, mid):
    return client.get(f"/api/v2/matches/{mid}", headers=u["h"]).json()


def _wait(pred, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.05)
    return False


def _onnx(in_shape, out_shape) -> bytes:
    rng = np.random.default_rng(0)
    w = rng.normal(size=(int(np.prod(in_shape)), int(np.prod(out_shape)))).astype(np.float32)
    b = np.zeros(int(np.prod(out_shape)), dtype=np.float32)
    graph = helper.make_graph(
        [helper.make_node("Flatten", ["x"], ["xf"], axis=1),
         helper.make_node("MatMul", ["xf", "W"], ["y"]),
         helper.make_node("Add", ["y", "B"], ["out"])], "m",
        [helper.make_tensor_value_info("x", TensorProto.FLOAT, list(in_shape))],
        [helper.make_tensor_value_info("out", TensorProto.FLOAT, list(out_shape))],
        [helper.make_tensor("W", TensorProto.FLOAT, list(w.shape), w.tobytes(), raw=True),
         helper.make_tensor("B", TensorProto.FLOAT, [b.size], b.tobytes(), raw=True)])
    return helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)]).SerializeToString()


def _model(u, game, in_shape, out_shape):
    r = client.post("/api/v1/models", headers=u["h"], data={"game": game, "name": f"m{next(_N)}"},
                    files={"file": ("m.onnx", _onnx(in_shape, out_shape), "application/octet-stream")})
    assert r.status_code == 200, r.text
    return r.json()["model"]["id"]


# ------------------------------------------------------------------ practice

def test_practice_match_plays_settles_records_and_seals_frames():
    u = _user()
    m = _create(u, game="snake", settings={"seed": 3})
    mid = m["id"]
    assert (m["status"], m["kind"], m["mode"], m["visibility"]) == \
        ("active", "pve", "practice", "unlisted")
    assert m["you"]["seat"] == "p0" and m["to_act"] == ["p0"] and m["deadline_at"] is None
    assert m["frame"]["seed"] == 3

    r = _act(u, mid, 5, 1)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "stale_tick"
    assert r.json()["detail"]["current"] == 0
    r = _act(u, mid, 0, 9)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_action"

    tick = 0
    while _view(u, mid)["status"] == "active":
        r = _act(u, mid, tick, 1)   # straight into the wall
        assert r.status_code == 202, r.text
        tick += 1
    final = _view(u, mid)
    assert final["status"] == "finished" and final["result"]["cause"]
    assert final["frames"] == tick + 1
    assert _act(u, mid, tick, 1).json()["detail"]["code"] == "match_over"

    frames = client.get(f"/api/v2/matches/{mid}/frames?from=0&limit=3", headers=u["h"]).json()
    assert [f["tick"] for f in frames["frames"]] == [0, 1, 2] and frames["total"] == tick + 1
    assert frames["frames"][1]["actions"] == {"p0": 1}

    rec = store.get_v2(mid)
    assert rec["status"] == "finished" and rec["kind"] == "pve" and Path(rec["frames"]).exists()
    assert rec["seats"] == [{"seat": "p0", "user_id": u["user"]["id"],
                             "controller": {"type": "human"}}]
    # the board entry comes from the server, not from the client
    board = client.get("/api/snake/scores?limit=50").json()["items"]
    assert any(i["name"] == u["user"]["username"] for i in board)

    # evicted from memory: snapshot and frames come from the record + sealed file
    engine.LIVE.pop(mid)
    old = _view(u, mid)
    assert old["status"] == "finished" and old["tick"] == tick and old["you"]["seat"] == "p0"
    sealed = client.get(f"/api/v2/matches/{mid}/frames?from={tick}", headers=u["h"])
    assert sealed.json()["frames"][0]["tick"] == tick
    assert "max-age" in sealed.headers["cache-control"]


def test_versus_ai_autopilot_and_takeover():
    u = _user()
    m = _create(u, game="microrts")
    mid = m["id"]
    assert [s["controller"]["type"] for s in m["seats"]] == ["human", "ai"]
    assert _act(u, mid, 0, []).status_code == 202
    first = client.get(f"/api/v2/matches/{mid}/frames?from=1", headers=u["h"]).json()["frames"][0]
    assert first["actions"]["p0"] == [] and isinstance(first["actions"]["p1"], list)

    # hand my seat to the built-in AI: the server plays it at a watchable pace
    r = client.post(f"/api/v2/matches/{mid}/controller", headers=u["h"],
                    json={"seat": "p0", "controller": {"type": "ai", "strategy": "worker_rush"}})
    assert r.status_code == 200, r.text
    start = _view(u, mid)["tick"]
    assert _wait(lambda: _view(u, mid)["tick"] >= start + 3)
    assert _act(u, mid, _view(u, mid)["tick"], []).json()["detail"]["code"] == "autopilot"
    client.post(f"/api/v2/matches/{mid}/controller", headers=u["h"],
                json={"seat": "p0", "controller": {"type": "human"}})
    time.sleep(0.6)
    held = _view(u, mid)["tick"]
    time.sleep(0.6)
    assert _view(u, mid)["tick"] == held   # back to manual: nothing moves by itself


def test_model_autopilot_and_model_vs_ai():
    u = _user()
    snake_model = _model(u, "snake", (1, 1334), (1, 3))
    m = _create(u, game="snake", seats=[{"seat": "p0", "occupant": "me",
                                         "controller": {"type": "model", "model_id": snake_model}}])
    assert m["seats"][0]["controller"]["type"] == "model"
    assert _wait(lambda: _view(u, m["id"])["status"] == "finished", timeout=30)
    rec = store.get_v2(m["id"])
    assert rec["models"][0]["model_id"] == snake_model

    rts_model = _model(u, "microrts", (1, 1546), (1, 140))
    vs = _create(u, game="microrts", seats=[
        {"seat": "p0", "occupant": None, "controller": {"type": "model", "model_id": rts_model}},
        {"seat": "p1", "occupant": None, "controller": {"type": "ai", "strategy": "worker_rush"}}])
    assert vs["kind"] == "model_vs_model" and vs["you"]["seat"] is None
    assert _wait(lambda: _view(u, vs["id"])["status"] == "finished", timeout=60)
    assert store.get_v2(vs["id"])["kind"] == "model_vs_model"


def test_create_validation():
    u, other = _user(), _user()
    foreign = _model(other, "snake", (1, 1334), (1, 3))
    cases = [
        ({"game": "nope"}, 404, "unknown_game"),
        ({"game": "snake", "seats": [{"seat": "p1", "occupant": "me"}]}, 400, "bad_seats"),
        ({"game": "snake", "seats": [{"seat": "p0", "occupant": "me", "controller":
                                      {"type": "model", "model_id": foreign}}]}, 403, "bad_controller"),
        ({"game": "snake", "mode": "ranked"}, 400, "bad_mode"),
        ({"game": "microrts", "seats": [
            {"seat": "p0", "occupant": "me", "controller": {"type": "ai"}},
            {"seat": "p1", "occupant": None, "controller": {"type": "human"}}]}, 400, "bad_seats"),
        ({"game": "snake", "settings": {"speed": 2}}, 400, "bad_settings"),
    ]
    for body, status, code in cases:
        r = client.post("/api/v2/matches", json=body, headers=u["h"])
        assert (r.status_code, r.json()["detail"]["code"]) == (status, code), (body, r.text)
    assert client.post("/api/v2/matches", json={"game": "snake"}).status_code == 401


# ------------------------------------------------------------------ rooms

def _room(host, **extra):
    return _create(host, game="microrts", seats=[
        {"seat": "p0", "occupant": "me", "controller": {"type": "human"}},
        {"seat": "p1", "occupant": None, "controller": {"type": "human"}}], **extra)


def test_room_join_turns_resign_rematch():
    a, b = _user(), _user()
    room = _room(a)
    mid = room["id"]
    assert (room["status"], room["kind"], room["mode"]) == ("waiting", "pvp", "casual")
    assert any(r["id"] == mid for r in client.get("/api/v2/matches?game=microrts").json()["rooms"])
    assert _act(a, mid, 0, []).json()["detail"]["code"] == "not_started"

    r = client.post(f"/api/v2/matches/{mid}/seats/p1/join", json={}, headers=b["h"])
    assert r.status_code == 200 and r.json()["status"] == "active"
    assert r.json()["deadline_at"] is not None and r.json()["you"]["seat"] == "p1"
    assert not any(x["id"] == mid for x in client.get("/api/v2/matches?game=microrts").json()["rooms"])
    assert {m["id"] for m in client.get("/api/v2/me/matches", headers=b["h"]).json()["matches"]} >= {mid}

    assert _act(a, mid, 0, []).status_code == 202
    assert _act(a, mid, 0, []).status_code == 202          # revising before resolve is fine
    v = _view(a, mid)
    assert v["tick"] == 0 and [s["submitted"] for s in v["seats"]] == [True, False]
    assert _act(b, mid, 0, []).status_code == 202
    assert _view(a, mid)["tick"] == 1

    assert client.post(f"/api/v2/matches/{mid}/resign", headers=b["h"]).json()["result"]["winner"] == "p0"
    rec = store.get_v2(mid)
    assert rec["result"]["cause"] == "resigned" and rec["kind"] == "pvp"

    offer = client.post(f"/api/v2/matches/{mid}/rematch", headers=b["h"]).json()
    assert offer["state"] == "offered" and offer["by"] == "p1"
    accepted = client.post(f"/api/v2/matches/{mid}/rematch", headers=a["h"]).json()
    assert accepted["state"] == "accepted"
    again = client.post(f"/api/v2/matches/{mid}/rematch", headers=b["h"]).json()
    assert again["match_id"] == accepted["match_id"]       # idempotent
    fresh = _view(a, accepted["match_id"])
    assert fresh["status"] == "active" and fresh["you"]["seat"] == "p1"   # sides swapped


def test_private_room_invites_and_visibility():
    a, b, c = _user(), _user(), _user()
    room = _room(a, visibility="private")
    mid = room["id"]
    assert room["invite"] and len(room["invite"]) == 6
    assert not any(r["id"] == mid for r in client.get("/api/v2/matches?game=microrts").json()["rooms"])
    r = client.post(f"/api/v2/matches/{mid}/seats/p1/join", json={"invite": "WRONG1"}, headers=b["h"])
    assert r.json()["detail"]["code"] == "bad_invite"
    r = client.post(f"/api/v2/matches/{mid}/seats/p1/join", json={"invite": room["invite"].lower()},
                    headers=b["h"])
    assert r.status_code == 200
    assert client.get(f"/api/v2/matches/{mid}", headers=c["h"]).status_code == 403
    assert client.get(f"/api/v2/matches/{mid}/frames", headers=c["h"]).status_code == 403
    assert client.get(f"/api/v2/matches/{mid}/chat", headers=c["h"]).status_code == 403
    assert client.post(f"/api/v2/matches/{mid}/chat", json={"text": "gg"}, headers=a["h"]).status_code == 200
    msgs = client.get(f"/api/v2/matches/{mid}/chat", headers=b["h"]).json()["messages"]
    assert [m["text"] for m in msgs] == ["gg"]


def test_deadline_auto_waits_then_forfeits(monkeypatch):
    monkeypatch.setattr(engine, "PVP_MOVE_TIMEOUT_S", 0.3)
    monkeypatch.setattr(engine, "PVP_MAX_TIMEOUTS", 2)
    a, b = _user(), _user()
    mid = _room(a)["id"]
    client.post(f"/api/v2/matches/{mid}/seats/p1/join", json={}, headers=b["h"])
    assert _act(a, mid, 0, []).status_code == 202
    assert _wait(lambda: _view(a, mid)["tick"] == 1)   # b timed out once: auto-wait
    assert _view(a, mid)["seats"][1]["timeouts"] == 1
    assert _act(a, mid, 1, []).status_code == 202
    assert _wait(lambda: _view(a, mid)["status"] == "finished")
    assert _view(a, mid)["result"] == {"winner": "p0", "cause": "timeout",
                                       "tick": _view(a, mid)["tick"]}


def test_matchmaking_v2_pairs_into_a_match():
    a, b = _user(), _user()
    assert client.post("/api/v2/microrts/matchmaking/queue", json={"mode": "casual"},
                       headers=a["h"]).json()["queued"]
    st = client.post("/api/v2/microrts/matchmaking/queue", json={"mode": "casual"},
                     headers=b["h"]).json()
    assert st["matched"] and st["match_id"]
    v = _view(a, st["match_id"])
    assert v["status"] == "active" and v["kind"] == "pvp" and v["you"]["seat"] == "p0"
    assert client.get("/api/v2/microrts/matchmaking/status", headers=a["h"]).json()["match_id"] \
        == st["match_id"]


# ------------------------------------------------------------------ failures

def test_engine_failure_aborts_and_restart_marks_live_matches(monkeypatch):
    u = _user()
    mid = _create(u, game="snake")["id"]
    adapter = registry.GAMES["snake"]

    def boom(*args, **kwargs):
        raise RuntimeError("sandbox down")
    monkeypatch.setattr(adapter, "step_state", boom)
    assert _act(u, mid, 0, 1).status_code == 202
    v = _view(u, mid)
    assert v["status"] == "aborted" and v["result"]["cause"] == "engine_error"
    assert "sandbox down" in v["result"]["detail"]
    monkeypatch.undo()

    live = _create(u, game="snake")["id"]
    engine.LIVE.pop(live)          # the process "restarted"
    assert store.abort_unfinished_v2() >= 1
    gone = _view(u, live)
    assert gone["status"] == "aborted" and gone["result"]["cause"] == "server_restart"


def test_sweep_cancels_unjoined_rooms_and_aborts_idle_matches():
    a = _user()
    room = _room(a)["id"]
    idle = _create(a, game="snake")["id"]
    engine.sweep(now=time.time() + engine.WAITING_TTL + 1)
    assert _view(a, room)["status"] == "cancelled"
    assert _view(a, idle)["status"] == "aborted" and _view(a, idle)["result"]["cause"] == "idle"
