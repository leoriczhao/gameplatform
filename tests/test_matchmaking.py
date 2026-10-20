"""Quick matchmaking tests (06 §5 / v1.0-a M2): pairing within the ELO
band, band relaxation, mode separation, cancel, timeout removal."""
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
import matchmaking  # noqa: E402

client = TestClient(main.app)


def _user(name):
    r = client.post("/api/v1/auth/register",
                    json={"username": name, "password": "password123"})
    assert r.status_code == 200, r.text
    return r.json()


class FakeTime:
    """Mutable clock for band/expiry tests (patched onto matchmaking._now)."""
    now = 1000000.0

    @staticmethod
    def time():
        return FakeTime.now


def _queue(user, mode="ranked"):
    return client.post("/api/v1/microrts/matchmaking/queue",
                       json={"mode": mode},
                       headers={"Authorization": f"Bearer {user['token']}"})


def _status(user):
    return client.get("/api/v1/microrts/matchmaking/status",
                      headers={"Authorization": f"Bearer {user['token']}"})


def _cancel(user):
    return client.delete("/api/v1/microrts/matchmaking/queue",
                         headers={"Authorization": f"Bearer {user['token']}"})


def _resign(user, sid):
    return client.post(f"/api/v1/microrts/play/sessions/{sid}/leave",
                       json={},
                       headers={"Authorization": f"Bearer {user['token']}"})


def test_matchmaking_requires_login():
    assert client.post("/api/v1/microrts/matchmaking/queue",
                       json={"mode": "ranked"}).status_code == 401
    assert client.get("/api/v1/microrts/matchmaking/status").status_code == 401
    assert client.delete("/api/v1/microrts/matchmaking/queue").status_code == 401


def test_pairing_creates_ranked_room_and_settles_elo():
    A = _user("mma1")
    B = _user("mmb1")

    r = _queue(A)
    assert r.status_code == 200, r.text
    assert r.json()["queued"] is True and r.json()["matched"] is False
    assert r.json()["position"] == 1

    # B enqueues -> both at 1200, inside the band -> matched immediately
    r = _queue(B)
    assert r.status_code == 200, r.text
    assert r.json()["matched"] is True
    sid = r.json()["session_id"]

    # A's entry still holds the room id until A polls
    r = _status(A)
    assert r.json()["matched"] is True and r.json()["session_id"] == sid

    # the matched room is an internal private ranked PvP room
    r = client.get(f"/api/v1/microrts/play/sessions/{sid}",
                   headers={"Authorization": f"Bearer {A['token']}"})
    s = r.json()["session"]
    assert s["status"] == "active" and s["p1_joined"] is True
    assert s["mode"] == "ranked" and s["visibility"] == "private"
    assert r.json()["side"] == "p0"          # earlier enqueuer is p0
    rooms = client.get("/api/v1/microrts/play/rooms",
                       headers={"Authorization": f"Bearer {A['token']}"}).json()["rooms"]
    assert all(rm["id"] != sid for rm in rooms)  # not in the public lobby list

    # both can play, then A resigns -> ranked settles ELO
    client.post(f"/api/v1/microrts/play/sessions/{sid}/actions",
                json={"actions": []},
                headers={"Authorization": f"Bearer {B['token']}"})
    client.post(f"/api/v1/microrts/play/sessions/{sid}/actions",
                json={"actions": []},
                headers={"Authorization": f"Bearer {A['token']}"})
    r = _resign(A, sid)
    assert r.status_code == 200 and r.json()["winner"] == 1
    r = client.get("/api/v1/ratings/microrts",
                   headers={"Authorization": f"Bearer {A['token']}"})
    ratings = {i["name"]: i for i in r.json()["items"]}
    assert ratings[B["user"]["username"]]["rating"] > 1200
    assert ratings[A["user"]["username"]]["rating"] < 1200

    # idempotent status: the room id stays readable until re-queue/cancel
    assert _status(A).json()["matched"] is True
    assert _status(B).json()["matched"] is True
    _cancel(A)
    _cancel(B)
    assert _status(A).json()["queued"] is False
    assert _status(B).json()["queued"] is False


def test_casual_pairing_does_not_change_elo():
    A = _user("mma2")
    B = _user("mmb2")
    _queue(A, mode="casual")
    r = _queue(B, mode="casual")
    assert r.json()["matched"] is True
    sid = r.json()["session_id"]
    assert _status(A).json()["session_id"] == sid
    _resign(A, sid)
    r = client.get("/api/v1/ratings/microrts",
                   headers={"Authorization": f"Bearer {A['token']}"})
    names = {i["name"] for i in r.json()["items"]}
    assert A["user"]["username"] not in names
    assert B["user"]["username"] not in names
    _cancel(A)
    _cancel(B)


def test_modes_do_not_cross():
    A = _user("mma3")
    B = _user("mmb3")
    _queue(A, mode="ranked")
    r = _queue(B, mode="casual")
    assert r.json()["matched"] is False and r.json()["queued"] is True
    assert _status(A).json()["matched"] is False
    _cancel(A)
    _cancel(B)
    assert _status(A).json()["queued"] is False
    assert _status(B).json()["queued"] is False


def test_cancel_removes_from_queue():
    A = _user("mma4")
    _queue(A)
    assert _status(A).json()["queued"] is True
    r = _cancel(A)
    assert r.status_code == 200 and r.json()["queued"] is False
    assert _status(A).json()["queued"] is False


def test_band_relaxes_then_matches(monkeypatch):
    A = _user("mma5")
    B = _user("mmb5")
    monkeypatch.setattr(matchmaking, "_now", FakeTime.time)
    monkeypatch.setattr(
        matchmaking, "get_rating",
        lambda game, uid: 1000.0 if uid == A["user"]["id"] else 1500.0)

    _queue(A)  # rating 1000
    r = _queue(B)  # rating 1500, diff 500 > 400 max band
    assert r.json()["matched"] is False

    # after 65s of waiting the ranked band is ∞ -> any opponent
    FakeTime.now += 65
    matchmaking.try_match()
    st = _status(A).json()
    assert st["matched"] is True
    sid = st["session_id"]
    stb = _status(B).json()
    assert stb["matched"] is True and stb["session_id"] == sid
    # cleanup: resign and clear queue state
    _resign(A, sid)
    _cancel(A)
    _cancel(B)


def test_queue_timeout_removes_entry(monkeypatch):
    A = _user("mma6")
    monkeypatch.setattr(matchmaking, "_now", FakeTime.time)
    monkeypatch.setattr(matchmaking, "QUEUE_TIMEOUT", 5)
    _queue(A)
    assert _status(A).json()["queued"] is True
    FakeTime.now += 11
    matchmaking.try_match()
    assert _status(A).json()["queued"] is False


def test_reenqueue_replaces_entry_and_mode():
    A = _user("mma7")
    _queue(A, mode="ranked")
    assert _status(A).json()["mode"] == "ranked"
    r = _queue(A, mode="casual")
    assert r.json()["queued"] is True and r.json()["mode"] == "casual"
    assert r.json()["position"] == 1
    _cancel(A)


def test_same_pair_not_rematched_while_unfinished():
    A = _user("mma8")
    B = _user("mmb8")
    _queue(A)
    r = _queue(B)
    assert r.json()["matched"] is True
    sid1 = _status(A).json()["session_id"]

    # re-queue both while the first room is still running -> no new pairing
    _queue(A)
    r = _queue(B)
    assert r.json()["matched"] is False

    # finish the first room -> the pair becomes eligible again
    _resign(A, sid1)
    matchmaking.try_match()
    r = _status(A)
    assert r.json()["matched"] is True
    sid2 = r.json()["session_id"]
    assert sid2 != sid1
    _resign(A, sid2)
    _cancel(B)
