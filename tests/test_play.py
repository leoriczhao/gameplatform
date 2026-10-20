"""Play session API tests (PvE v1): create/step/leave/replay, login, errors.

Play now requires a registered account; guests may only read public rooms.
"""
import os
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

_tmp = tempfile.TemporaryDirectory()
os.environ["SCORES_DB"] = str(Path(_tmp.name) / "scores.db")

from fastapi.testclient import TestClient  # noqa: E402

import api_limits  # noqa: E402
import main  # noqa: E402

client = TestClient(main.app)

# registered user used by most tests
USER = client.post("/api/v1/auth/register",
                   json={"username": "playuser1", "password": "password123"}
                   ).json()
USER_HEADERS = {"Authorization": f"Bearer {USER['token']}"}


def _create(game, **kw):
    r = client.post(f"/api/v1/{game}/play/sessions", json=kw,
                    headers=USER_HEADERS)
    assert r.status_code == 200, r.text
    return r.json()["session"]


def _leave(game, sid):
    client.post(f"/api/v1/{game}/play/sessions/{sid}/leave",
                headers=USER_HEADERS)


def test_snake_session_lifecycle():
    s = _create("snake", seed=42)
    assert s["status"] == "active" and s["tick"] == 0
    assert s["state"]["seed"] == 42

    r = client.post(f"/api/v1/snake/play/sessions/{s['id']}/actions",
                    json={"actions": 1}, headers=USER_HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert body["tick"] == 1 and body["done"] is False

    r = client.post(f"/api/v1/snake/play/sessions/{s['id']}/actions",
                    json={"actions": 9}, headers=USER_HEADERS)
    assert r.status_code == 400  # invalid action

    r = client.get(f"/api/v1/snake/play/sessions/{s['id']}",
                   headers=USER_HEADERS)
    assert r.json()["session"]["tick"] == 1

    r = client.post(f"/api/v1/snake/play/sessions/{s['id']}/leave",
                    headers=USER_HEADERS)
    assert r.json()["status"] == "abandoned"

    r = client.post(f"/api/v1/snake/play/sessions/{s['id']}/actions",
                    json={"actions": 1}, headers=USER_HEADERS)
    assert r.status_code == 409  # stepping an abandoned session

    r = client.get(f"/api/v1/snake/play/sessions/{s['id']}/replay",
                   headers=USER_HEADERS)
    assert r.status_code == 200
    assert len(r.json()["moves"]) == 1


def test_snake_session_deterministic_with_seed():
    a = _create("snake", seed=7)
    b = _create("snake", seed=7)
    assert a["state"] == b["state"]
    _leave("snake", a["id"])
    _leave("snake", b["id"])


def test_tetris_session_steps():
    s = _create("tetris", seed=3)
    r = client.post(f"/api/v1/tetris/play/sessions/{s['id']}/actions",
                    json={"actions": 3}, headers=USER_HEADERS)  # hard drop
    assert r.status_code == 200
    assert r.json()["tick"] == 1
    _leave("tetris", s["id"])


def test_microrts_session_with_builtin_opponent():
    s = _create("microrts", seed=5,
                opponent={"type": "ai", "strategy": "worker_rush"})
    assert s["state"]["opponent"] == "external"
    base0 = s["state"]["units"][0]["id"]
    for _ in range(60):
        api_limits._hits.clear()  # play/actions 限流 30 req/s，测试内隔离
        st = client.get(f"/api/v1/microrts/play/sessions/{s['id']}",
                        headers=USER_HEADERS).json()["session"]["state"]
        r = client.post(f"/api/v1/microrts/play/sessions/{s['id']}/actions",
                        json={"actions": [[base0, 5, 1, "worker"]]
                              if st["bank"][0] >= 1 and not st["done"] else []},
                        headers=USER_HEADERS)
        assert r.status_code == 200, r.text
        if r.json()["done"]:
            break
    assert r.json()["tick"] >= 1
    st = client.get(f"/api/v1/microrts/play/sessions/{s['id']}",
                    headers=USER_HEADERS).json()["session"]["state"]
    # the opponent (red side) acted too: it produces workers with its gold
    assert any(u["owner"] == 1 and u["type"] == "worker" for u in st["units"])
    _leave("microrts", s["id"])


def test_microrts_invalid_opponent_400():
    r = client.post("/api/v1/microrts/play/sessions",
                    json={"opponent": {"type": "skynet"}},
                    headers=USER_HEADERS)
    assert r.status_code == 400


def test_unknown_game_and_session_404():
    r = client.post("/api/v1/nope/play/sessions", json={},
                    headers=USER_HEADERS)
    assert r.status_code == 404
    r = client.get("/api/v1/snake/play/sessions/deadbeef",
                   headers=USER_HEADERS)
    assert r.status_code == 404


def test_play_requires_login():
    """游客只能看：公开房间列表可读，创建任何游玩会话都 401。"""
    assert client.get("/api/v1/snake/play/rooms").status_code == 200
    assert client.post("/api/v1/snake/play/sessions",
                       json={}).status_code == 401
    assert client.post("/api/v1/snake/play/sessions",
                       json={"kind": "pvp"}).status_code == 401


def test_actions_expected_tick_conflict():
    s = _create("snake", seed=1)
    r = client.post(f"/api/v1/snake/play/sessions/{s['id']}/actions",
                    json={"actions": 1, "expected_tick": 5},
                    headers=USER_HEADERS)
    assert r.status_code == 409, r.text  # stale tick -> refresh and retry
    r = client.post(f"/api/v1/snake/play/sessions/{s['id']}/actions",
                    json={"actions": 1, "expected_tick": 0},
                    headers=USER_HEADERS)
    assert r.status_code == 200, r.text
    assert r.json()["tick"] == 1
    _leave("snake", s["id"])


def test_pve_session_is_owner_only():
    s = _create("snake", seed=2)
    other = client.post("/api/v1/auth/register",
                        json={"username": "playuser2",
                              "password": "password123"}).json()
    headers = {"Authorization": f"Bearer {other['token']}"}
    r = client.post(f"/api/v1/snake/play/sessions/{s['id']}/actions",
                    json={"actions": 1}, headers=headers)
    assert r.status_code == 403, r.text
    r = client.post(f"/api/v1/snake/play/sessions/{s['id']}/leave",
                    headers=headers)
    assert r.status_code == 403, r.text
    _leave("snake", s["id"])
