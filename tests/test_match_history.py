"""Retained history API (design 17 §6/§9): reads survive the v1 cutover.

Match creation/mutation is v2-only, but the archived history projection stays:
GET /api/v1/matches (list), GET /api/v1/matches/{id} (detail) and
GET /api/v1/ratings/{game} (ELO board) keep reading v2 records and migrated
v1 rows. This file replaces the coverage lost when test_rooms/test_pvp were
deleted.
"""
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
import matches as store  # noqa: E402

client = TestClient(main.app)
_N = iter(range(10_000))


def _user(prefix="hist"):
    name = f"{prefix}{next(_N)}{os.getpid() % 1000}"
    r = client.post("/api/v1/auth/register",
                    json={"username": name, "password": "password123"})
    assert r.status_code == 200, r.text
    u = r.json()
    u["h"] = {"Authorization": f"Bearer {u['token']}"}
    return u


def _finished_ranked_pvp() -> tuple[dict, dict, str, int]:
    """A creates a ranked room, B joins, B resigns -> A wins. Returns ids."""
    a, b = _user("ha"), _user("hb")
    r = client.post("/api/v2/matches", headers=a["h"], json={
        "game": "microrts", "mode": "ranked",
        "seats": [{"seat": "p0", "occupant": "me", "controller": {"type": "human"}},
                  {"seat": "p1", "occupant": None, "controller": {"type": "human"}}]})
    assert r.status_code == 201, r.text
    uid = r.json()["id"]
    r = client.post(f"/api/v2/matches/{uid}/seats/p1/join", json={}, headers=b["h"])
    assert r.status_code == 200, r.text
    r = client.post(f"/api/v2/matches/{uid}/resign", headers=b["h"])
    assert r.status_code == 200, r.text
    rec = store.get_v2(uid)
    assert rec["status"] == "finished" and rec["result"]["winner"] == "p0"
    return a, b, uid, rec["row_id"]


def test_history_list_detail_and_ratings_stay_for_v2_records():
    a, b, uid, row_id = _finished_ranked_pvp()

    response = client.get("/api/v1/matches", headers=a["h"])
    assert response.status_code == 200, response.text
    row = next(m for m in response.json()["matches"] if m["id"] == row_id)
    assert row["uid"] == uid and row["kind"] == "pvp" and row["status"] == "finished"
    assert row["mode"] == "ranked" and row["result"]["winner"] == "p0"
    assert row["game"] == "microrts"
    # the loser's own history carries the same row
    assert any(m["id"] == row_id
               for m in client.get("/api/v1/matches", headers=b["h"]).json()["matches"])

    detail = client.get(f"/api/v1/matches/{row_id}", headers=a["h"])
    assert detail.status_code == 200, detail.text
    assert detail.json()["match"]["uid"] == uid
    assert client.get("/api/v1/matches/99999999", headers=a["h"]).status_code == 404

    # ratings: ranked settlement moved ELO for both sides
    r = client.get("/api/v1/ratings/microrts", headers=a["h"])
    assert r.status_code == 200, r.text
    items = {i["user_id"]: i for i in r.json()["items"]}
    assert items[a["user"]["id"]]["rating"] > 1200
    assert items[b["user"]["id"]]["rating"] < 1200
    assert items[a["user"]["id"]]["wins"] >= 1

    # login is still required on the history surface
    assert client.get("/api/v1/matches").status_code == 401
    assert client.get(f"/api/v1/matches/{row_id}").status_code == 401
    assert client.get("/api/v1/ratings/microrts").status_code == 401
