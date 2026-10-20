"""Reconnect + rematch tests (06 §7 U5/U7 / v1.0-a M3)."""
import os
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

_tmp = tempfile.TemporaryDirectory()
os.environ["SCORES_DB"] = str(Path(_tmp.name) / "scores.db")
os.environ["MODELS_DIR"] = str(Path(_tmp.name) / "models")

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402

client = TestClient(main.app)


def _user(name):
    r = client.post("/api/v1/auth/register",
                    json={"username": name, "password": "password123"})
    assert r.status_code == 200, r.text
    return r.json()


def _active(user):
    r = client.get("/api/v1/play/active",
                   headers={"Authorization": f"Bearer {user['token']}"})
    assert r.status_code == 200, r.text
    return r.json()["sessions"]


def test_active_requires_login():
    assert client.get("/api/v1/play/active").status_code == 401


def test_active_lists_my_waiting_and_active_sessions_only():
    A = _user("rca1")
    B = _user("rcb1")
    C = _user("rcc1")
    HA = {"Authorization": f"Bearer {A['token']}"}
    HB = {"Authorization": f"Bearer {B['token']}"}

    # A creates a waiting room
    r = client.post("/api/v1/microrts/play/rooms",
                    json={"mode": "casual", "visibility": "private"}, headers=HA)
    sid = r.json()["session"]["id"]
    invite = r.json()["invite"]

    # A sees it (waiting, side p0); B and C do not
    a_sessions = _active(A)
    assert any(s["id"] == sid and s["status"] == "waiting" and s["side"] == "p0"
               for s in a_sessions)
    assert all(s["id"] != sid for s in _active(B))
    assert all(s["id"] != sid for s in _active(C))

    # B joins -> active; both players now see it with their own sides
    client.post(f"/api/v1/microrts/play/rooms/{sid}/join",
                json={"invite": invite}, headers=HB)
    b_sessions = _active(B)
    assert any(s["id"] == sid and s["status"] == "active" and s["side"] == "p1"
               for s in b_sessions)
    assert any(s["id"] == sid and s["status"] == "active" and s["side"] == "p0"
               for s in _active(A))
    assert all(s["id"] != sid for s in _active(C))  # spectators don't appear

    # finished sessions leave the list
    client.post(f"/api/v1/microrts/play/sessions/{sid}/leave", headers=HA)
    assert all(s["id"] != sid for s in _active(A))
    assert all(s["id"] != sid for s in _active(B))


def test_rematch_swaps_sides_and_copies_settings():
    A = _user("rca2")
    B = _user("rcb2")
    HA = {"Authorization": f"Bearer {A['token']}"}
    HB = {"Authorization": f"Bearer {B['token']}"}

    r = client.post("/api/v1/microrts/play/rooms",
                    json={"mode": "casual", "visibility": "private",
                          "settings": {"seed": 42}}, headers=HA)
    sid = r.json()["session"]["id"]
    invite = r.json()["invite"]
    client.post(f"/api/v1/microrts/play/rooms/{sid}/join",
                json={"invite": invite}, headers=HB)

    # rematch only works on finished games
    r = client.post(f"/api/v1/microrts/play/sessions/{sid}/rematch",
                    json={}, headers=HA)
    assert r.status_code == 400

    # play one tick then A resigns -> finished
    client.post(f"/api/v1/microrts/play/sessions/{sid}/actions",
                json={"actions": []}, headers=HB)
    client.post(f"/api/v1/microrts/play/sessions/{sid}/actions",
                json={"actions": []}, headers=HA)
    client.post(f"/api/v1/microrts/play/sessions/{sid}/leave", headers=HA)

    # A (old p0) calls rematch -> new room, sides swapped: A is now p1
    r = client.post(f"/api/v1/microrts/play/sessions/{sid}/rematch",
                    json={}, headers=HA)
    assert r.status_code == 200, r.text
    new_sid = r.json()["session"]["id"]
    assert new_sid != sid
    assert r.json()["session"]["status"] == "active"
    assert r.json()["side"] == "p1"          # swapped
    assert r.json()["session"]["mode"] == "casual"
    assert r.json()["session"]["visibility"] == "private"
    assert r.json()["session"]["state"]["seed"] == 42   # settings copied

    # B's active list shows the same new room as p0 (swapped)
    b_sessions = _active(B)
    assert any(s["id"] == new_sid and s["side"] == "p0" for s in b_sessions)

    # both can play in the rematch room
    client.post(f"/api/v1/microrts/play/sessions/{new_sid}/actions",
                json={"actions": []}, headers=HB)
    r = client.post(f"/api/v1/microrts/play/sessions/{new_sid}/actions",
                    json={"actions": []}, headers=HA)
    assert r.json()["advanced"] is True


def test_rematch_idempotent_and_restricted():
    A = _user("rca3")
    B = _user("rcb3")
    C = _user("rcc3")
    HA = {"Authorization": f"Bearer {A['token']}"}
    HB = {"Authorization": f"Bearer {B['token']}"}
    HC = {"Authorization": f"Bearer {C['token']}"}

    r = client.post("/api/v1/microrts/play/rooms",
                    json={"mode": "casual", "visibility": "private"}, headers=HA)
    sid = r.json()["session"]["id"]
    invite = r.json()["invite"]
    client.post(f"/api/v1/microrts/play/rooms/{sid}/join",
                json={"invite": invite}, headers=HB)
    client.post(f"/api/v1/microrts/play/sessions/{sid}/leave", headers=HA)

    # non-players cannot rematch
    r = client.post(f"/api/v1/microrts/play/sessions/{sid}/rematch",
                    json={}, headers=HC)
    assert r.status_code == 403

    # both original players clicking rematch land in the SAME new room
    r1 = client.post(f"/api/v1/microrts/play/sessions/{sid}/rematch",
                     json={}, headers=HA)
    r2 = client.post(f"/api/v1/microrts/play/sessions/{sid}/rematch",
                     json={}, headers=HB)
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json()["session"]["id"] == r2.json()["session"]["id"]
    assert r1.json()["side"] == "p1" and r2.json()["side"] == "p0"

    # unknown / non-pvp sessions -> 404
    assert client.post("/api/v1/microrts/play/sessions/nope/rematch",
                       json={}, headers=HA).status_code == 404
    r = client.post("/api/v1/microrts/play/sessions",
                    json={"kind": "pve"}, headers=HA)
    pve_sid = r.json()["session"]["id"]
    r = client.post(f"/api/v1/microrts/play/sessions/{pve_sid}/rematch",
                    json={}, headers=HA)
    assert r.status_code == 404
    client.post(f"/api/v1/microrts/play/sessions/{pve_sid}/leave", headers=HA)


def test_pve_sessions_in_active_list():
    A = _user("rca4")
    HA = {"Authorization": f"Bearer {A['token']}"}
    r = client.post("/api/v1/microrts/play/sessions",
                    json={"kind": "pve", "seed": 7}, headers=HA)
    sid = r.json()["session"]["id"]
    sessions = _active(A)
    assert any(s["id"] == sid and s["kind"] == "pve" and s["side"] == "p0"
               for s in sessions)
    client.post(f"/api/v1/microrts/play/sessions/{sid}/leave", headers=HA)
