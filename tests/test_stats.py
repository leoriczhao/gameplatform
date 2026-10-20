"""Growth & leaderboard tests (v1.0-c, numbers in docs/design/08)."""
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

import growth  # noqa: E402
import main  # noqa: E402

client = TestClient(main.app)


def _user(name):
    r = client.post("/api/v1/auth/register",
                    json={"username": name, "password": "password123"})
    assert r.status_code == 200, r.text
    return r.json()


def _h(u):
    return {"Authorization": f"Bearer {u['token']}"}


def _pvp_room(a, b, mode="casual"):
    r = client.post("/api/v1/microrts/play/rooms",
                    json={"mode": mode, "visibility": "private"}, headers=_h(a))
    sid = r.json()["session"]["id"]
    client.post(f"/api/v1/microrts/play/rooms/{sid}/join",
                json={"invite": r.json()["invite"]}, headers=_h(b))
    return sid


def _stats(u):
    r = client.get("/api/v1/stats/me", headers=_h(u))
    assert r.status_code == 200, r.text
    return r.json()


def test_level_curve():
    assert growth.level_of(0) == 1
    assert growth.level_of(99) == 1
    assert growth.level_of(100) == 2
    assert growth.level_of(299) == 2
    assert growth.level_of(300) == 3
    assert growth.level_of(600) == 4
    assert growth.level_of(1000) == 5
    assert abs(growth.level_progress(50) - 0.5) < 1e-9
    assert growth.level_progress(0) == 0.0
    assert growth.level_progress(300) == 0.0  # just reached L3


def test_pvp_xp_stats_streak_and_history():
    A = _user("staa1")
    B = _user("stab1")

    # game 1 (casual): B resigns -> A wins. A +25, B +10
    sid1 = _pvp_room(A, B, "casual")
    client.post(f"/api/v1/microrts/play/sessions/{sid1}/leave", headers=_h(B))
    # game 2 (ranked): B resigns again -> A wins. A +25, B +10; ELO + history
    sid2 = _pvp_room(A, B, "ranked")
    client.post(f"/api/v1/microrts/play/sessions/{sid2}/leave", headers=_h(B))

    sa = _stats(A)
    sb = _stats(B)
    print("A stats:", sa["totals"], "xp:", sa["xp"])
    print("B stats:", sb["totals"], "xp:", sb["xp"])
    assert sa["xp"] == 50 and sa["level"] == 1
    assert abs(sa["level_progress"] - 0.5) < 1e-9
    assert sa["totals"] == {"games": 2, "wins": 2, "losses": 0, "draws": 0,
                            "win_rate": 1.0, "current_streak": 2,
                            "best_streak": 2, "play_seconds": sa["totals"]["play_seconds"]}
    assert sb["xp"] == 20
    assert sb["totals"]["games"] == 2 and sb["totals"]["wins"] == 0
    assert sb["totals"]["losses"] == 2 and sb["totals"]["current_streak"] == 0

    # per-game breakdown + ELO history (ranked game only)
    ga = sa["games"]["microrts"]
    gb = sb["games"]["microrts"]
    assert ga["games"] == 2 and ga["wins"] == 2 and ga["rating"] > 1200
    assert gb["games"] == 2 and gb["wins"] == 0 and gb["rating"] < 1200
    assert len(ga["history"]) == 1 and len(gb["history"]) == 1
    assert ga["history"][0]["rating"] == ga["rating"]

    # profile carries xp/level too
    p = client.get("/api/v1/profile", headers=_h(A)).json()["profile"]
    assert p["xp"] == 50 and p["level"] == 1


def test_pve_finish_awards_xp():
    A = _user("staa2")
    r = client.post("/api/v1/snake/play/sessions",
                    json={"kind": "pve", "seed": 5}, headers=_h(A))
    sid = r.json()["session"]["id"]
    # keep going right until the snake hits the wall (deterministic)
    done = False
    for _ in range(50):
        r = client.post(f"/api/v1/snake/play/sessions/{sid}/actions",
                        json={"actions": 1}, headers=_h(A))
        assert r.status_code == 200, r.text
        if r.json()["done"]:
            done = True
            break
    assert done, "snake session should end within 50 wall-steps"
    s = _stats(A)
    print("pve xp:", s["xp"])
    assert s["xp"] >= 5


def test_leaderboards_total_and_weekly():
    A = _user("staa3")
    B = _user("stab3")
    sid = _pvp_room(A, B, "ranked")
    client.post(f"/api/v1/microrts/play/sessions/{sid}/leave", headers=_h(B))

    r = client.get("/api/v1/leaderboards/microrts?scope=weekly", headers=_h(A))
    assert r.status_code == 200, r.text
    weekly = {i["name"]: i for i in r.json()["items"]}
    print("weekly:", [(i["name"], i["wins"], i["games"]) for i in r.json()["items"]])
    assert weekly[A["user"]["username"]]["wins"] == 1
    assert weekly[B["user"]["username"]]["wins"] == 0
    # the winner ranks above the loser (board spans all users in the window)
    names = [i["name"] for i in r.json()["items"]]
    assert names.index(A["user"]["username"]) < names.index(B["user"]["username"])

    r = client.get("/api/v1/leaderboards/microrts?scope=total", headers=_h(A))
    total = {i["name"]: i for i in r.json()["items"]}
    assert total[A["user"]["username"]]["rating"] > 1200
    assert total[B["user"]["username"]]["rating"] < 1200

    # validation: bad scope / unknown game / login required
    assert client.get("/api/v1/leaderboards/microrts?scope=banana",
                      headers=_h(A)).status_code == 422
    assert client.get("/api/v1/leaderboards/nope",
                      headers=_h(A)).status_code == 404
    assert client.get("/api/v1/leaderboards/microrts").status_code == 401
    assert client.get("/api/v1/stats/me").status_code == 401
