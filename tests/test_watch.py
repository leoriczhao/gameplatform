"""Spectate + replay endpoint tests (06 §7 U6 / v1.0-a M4)."""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

_tmp = tempfile.TemporaryDirectory()
os.environ["SCORES_DB"] = str(Path(_tmp.name) / "scores.db")
os.environ["MODELS_DIR"] = str(Path(_tmp.name) / "models")

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
import matches as match_store  # noqa: E402
from openenv_helpers import environment_info  # noqa: E402

client = TestClient(main.app)


def _user(name):
    r = client.post("/api/v1/auth/register",
                    json={"username": name, "password": "password123"})
    assert r.status_code == 200, r.text
    return r.json()


def _headers(u):
    return {"Authorization": f"Bearer {u['token']}"}


def _play_one_finished_pvp(mode="casual", visibility="public"):
    """A creates, B joins, one tick, A resigns. Returns (A, B, match_id)."""
    A = _user(f"wa{int(time.time() * 1000) % 1000000}")
    B = _user(f"wb{int(time.time() * 1000) % 1000000}")
    r = client.post("/api/v1/microrts/play/rooms",
                    json={"mode": mode, "visibility": visibility,
                          "settings": {"seed": 4242}}, headers=_headers(A))
    sid = r.json()["session"]["id"]
    invite = r.json()["invite"]
    if visibility == "private":
        client.post(f"/api/v1/microrts/play/rooms/{sid}/join",
                    json={"invite": invite}, headers=_headers(B))
    else:
        client.post(f"/api/v1/microrts/play/rooms/{sid}/join",
                    json={}, headers=_headers(B))
    client.post(f"/api/v1/microrts/play/sessions/{sid}/actions",
                json={"actions": []}, headers=_headers(B))
    client.post(f"/api/v1/microrts/play/sessions/{sid}/actions",
                json={"actions": []}, headers=_headers(A))
    client.post(f"/api/v1/microrts/play/sessions/{sid}/leave", headers=_headers(A))
    r = client.get("/api/v1/matches", headers=_headers(A))
    pvp = [m for m in r.json()["matches"]
           if m["kind"] == "pvp" and m["status"] == "finished"
           and m["result"]["cause"] == "resigned"]
    assert pvp
    return A, B, pvp[0]["id"]


def test_replay_endpoint_is_public_with_seed_and_moves():
    A, B, match_id = _play_one_finished_pvp()
    # no auth header at all -> share links open directly
    r = client.get(f"/api/v1/matches/{match_id}/replay")
    assert r.status_code == 200, r.text
    rep = r.json()["replay"]
    assert rep["schema_version"] == 1
    assert rep["match_id"] == match_id
    assert rep["game"] == "microrts" and rep["kind"] == "pvp"
    assert rep["game_version"] == \
        environment_info(client, "microrts")["version"]
    assert rep["options"] == {"opponent": "external"}
    assert rep["mode"] == "casual"
    assert len(rep["players"]) == 2
    assert {p["side"] for p in rep["players"]} == {"p0", "p1"}
    assert rep["seed"] == 4242
    assert rep["result"]["winner"] == 1
    # one tick was played -> one move entry with both sides' commands
    assert len(rep["moves"]) == 1
    assert set(rep["moves"][0]["action"].keys()) == {"p0", "p1"}


def test_replay_404_for_missing_match():
    r = client.get("/api/v1/matches/99999999/replay")
    assert r.status_code == 404


def test_replay_legacy_plain_moves_format():
    """Old rows store replay as a plain moves list (no seed): the endpoint
    must still serve them (seed=None, moves passthrough)."""
    conn = match_store._db()
    try:
        cur = conn.execute(
            "INSERT INTO matches (game, kind, players, models, status, result, "
            "replay, created_at, finished_at) VALUES (?,?,?,?,?,?,?,?,?)",
            ("microrts", "pvp", json.dumps([{"user_id": 1, "name": "x", "side": "p0"},
                                            {"user_id": 2, "name": "y", "side": "p1"}]),
             "[]", "finished", json.dumps({"winner": 0, "cause": "resigned",
                                           "mode": "ranked"}),
             json.dumps([{"tick": 0, "action": {"p0": [], "p1": []}}]),
             time.time(), time.time()))
        conn.commit()
        legacy_id = cur.lastrowid
    finally:
        conn.close()
    r = client.get(f"/api/v1/matches/{legacy_id}/replay")
    assert r.status_code == 200, r.text
    rep = r.json()["replay"]
    assert rep["schema_version"] == 1
    assert rep["game_version"] is None and rep["options"] is None
    assert rep["seed"] is None
    assert len(rep["moves"]) == 1


def test_spectate_public_room_read_only():
    A = _user("wspec1")
    B = _user("wspec2")
    C = _user("wspec3")
    r = client.post("/api/v1/microrts/play/rooms",
                    json={"mode": "casual", "visibility": "public"}, headers=_headers(A))
    sid = r.json()["session"]["id"]
    client.post(f"/api/v1/microrts/play/rooms/{sid}/join", json={}, headers=_headers(B))

    # third account can watch (side null) while the game is running
    r = client.get(f"/api/v1/microrts/play/sessions/{sid}", headers=_headers(C))
    assert r.status_code == 200, r.text
    assert r.json()["side"] is None
    assert len(r.json()["session"]["players"]) == 2

    # even logged-out spectators can watch public games
    r = client.get(f"/api/v1/microrts/play/sessions/{sid}")
    assert r.status_code == 200 and r.json()["side"] is None

    # but they cannot act
    r = client.post(f"/api/v1/microrts/play/sessions/{sid}/actions",
                    json={"actions": []}, headers=_headers(C))
    assert r.status_code == 403


def test_spectate_private_room_forbidden():
    A = _user("wspec4")
    B = _user("wspec5")
    C = _user("wspec6")
    r = client.post("/api/v1/microrts/play/rooms",
                    json={"mode": "casual", "visibility": "private"}, headers=_headers(A))
    sid = r.json()["session"]["id"]
    client.post(f"/api/v1/microrts/play/rooms/{sid}/join",
                json={"invite": r.json()["invite"]}, headers=_headers(B))

    r = client.get(f"/api/v1/microrts/play/sessions/{sid}", headers=_headers(C))
    assert r.status_code == 403
    r = client.get(f"/api/v1/microrts/play/sessions/{sid}")
    assert r.status_code == 403
    # players still can
    assert client.get(f"/api/v1/microrts/play/sessions/{sid}",
                      headers=_headers(A)).status_code == 200


def test_spectate_matchmaking_game_allowed():
    A = _user("wspec7")
    B = _user("wspec8")
    C = _user("wspec9")
    client.post("/api/v1/microrts/matchmaking/queue",
                json={"mode": "casual"}, headers=_headers(A))
    r = client.post("/api/v1/microrts/matchmaking/queue",
                    json={"mode": "casual"}, headers=_headers(B))
    assert r.json()["matched"] is True
    sid = r.json()["session_id"]
    # matched games are watchable by anyone (06 §7), although the room itself
    # is internal/private
    r = client.get(f"/api/v1/microrts/play/sessions/{sid}", headers=_headers(C))
    assert r.status_code == 200, r.text
    assert r.json()["side"] is None
