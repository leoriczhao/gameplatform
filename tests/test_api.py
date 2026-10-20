"""Platform API integration tests via FastAPI TestClient."""
import os
import sys
import tempfile
import uuid
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

# use a throwaway SQLite file, never the real /data/scores.db
_tmp = tempfile.TemporaryDirectory()
os.environ["SCORES_DB"] = str(Path(_tmp.name) / "scores.db")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import api_limits  # noqa: E402
import main  # noqa: E402
import registry  # noqa: E402
from openenv_helpers import (  # noqa: E402
    environment_info, ws_message, ws_reset, ws_state, ws_step,
)
from ugc_runner import WorkerError  # noqa: E402


client = TestClient(main.app)


def _user_headers() -> dict:
    username = f"score_{uuid.uuid4().hex[:10]}"
    r = client.post("/api/v1/auth/register",
                    json={"username": username, "password": "password123"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _play_snake_to_end(headers: dict, seed: int = 0) -> tuple[int, int]:
    """Play a PvE snake session into the wall; return (match_id, score)."""
    r = client.post("/api/v1/snake/play/sessions",
                    json={"kind": "pve", "seed": seed}, headers=headers)
    assert r.status_code == 200, r.text
    sid = r.json()["session"]["id"]
    for _ in range(30):
        api_limits._hits.clear()  # play/actions 限流 30 req/s，测试内隔离
        r = client.post(f"/api/v1/snake/play/sessions/{sid}/actions",
                        json={"actions": 1}, headers=headers)
        assert r.status_code == 200, r.text
        body = r.json()
        if body["done"]:
            assert body["match_id"], body
            return int(body["match_id"]), int(body["state"]["score"])
    raise AssertionError("snake session did not finish")


def test_games_catalog():
    r = client.get("/api/games")
    assert r.status_code == 200
    ids = {g["id"] for g in r.json()["games"]}
    assert ids == {"snake", "tetris", "microrts"}
    for game in r.json()["games"]:
        assert "env_info_url" not in game
        assert game["schema_url"] == f"/api/openenv/{game['id']}/schema"
        assert game["openenv_url"] == f"/api/openenv/{game['id']}"
    snake = next(g for g in r.json()["games"] if g["id"] == "snake")
    assert snake["has_ai"] is True
    assert snake["page_url"] == "/games/snake/"
    assert snake["score_bounds"] == [0, 1000]
    rts = next(g for g in r.json()["games"] if g["id"] == "microrts")
    assert rts["has_ai"] is True
    assert rts["score_bounds"] == [0, 5000]


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert set(data["games"]) == {"snake", "tetris", "microrts"}


def test_snake_openenv_info_and_roundtrip():
    info = environment_info(client, "snake")
    assert info["game"] == "snake" and info["grid"] == [20, 20]
    assert info["max_concurrent_envs"] == 64

    with client.websocket_connect("/api/openenv/snake/ws") as ws:
        data = ws_reset(ws, seed=42, obs_mode="grid", include_state=True)
        obs = data["observation"]
        assert obs["state"]["seed"] == 42
        assert obs["type"] == "tensor" and obs["shape"] == [3, 22, 22]
        assert obs["dtype"] == "float32"
        assert len(obs["data"]) == 3 and len(obs["data"][0]) == 22
        assert obs["metadata"]["environment"] == info

        res = ws_step(ws, 1)
        assert res["observation"]["state"]["tick"] == 1
        assert "reward" in res and "done" in res
        assert "ate" in res["observation"]["metadata"]
        state = ws_state(ws)
        assert state["step_count"] == 1
        assert state["game_state"] == res["observation"]["state"]
        assert state["environment"] == info


def test_tetris_openenv_info_and_roundtrip():
    info = environment_info(client, "tetris")
    assert info["game"] == "tetris" and info["grid"] == [10, 20]
    assert info["actions"]["3"] == "hard_drop"
    assert info["max_concurrent_envs"] == 64

    with client.websocket_connect("/api/openenv/tetris/ws") as ws:
        data = ws_reset(ws, seed=7, obs_mode="grid", include_state=True)
        obs = data["observation"]
        assert obs["state"]["piece"]["id"] in range(7)
        assert obs["type"] == "tensor" and obs["shape"] == [2, 20, 10]
        assert len(obs["data"]) == 2 and len(obs["data"][0]) == 20
        assert obs["metadata"]["environment"] == info

        res = ws_step(ws, 3)
        assert res["observation"]["state"]["tick"] == 1
        assert res["done"] in (True, False)


def test_independent_openenv_sessions_with_custom_rewards():
    rewards = {"food": 10.0, "step": -0.1, "death": -10.0}
    with (client.websocket_connect("/api/openenv/snake/ws") as ws1,
          client.websocket_connect("/api/openenv/snake/ws") as ws2):
        s1 = ws_reset(ws1, seed=1, obs_mode="state", rewards=rewards)
        s2 = ws_reset(ws2, seed=2, obs_mode="state", rewards=rewards)
        assert s1["observation"]["type"] == s2["observation"]["type"] == "state"
        assert s1["observation"]["state"]["seed"] == 1
        assert s2["observation"]["state"]["seed"] == 2
        first = ws_step(ws1, 0)
        assert ws_state(ws2)["game_state"] == s2["observation"]["state"]
        second = ws_step(ws2, 2)
        for res in (first, second):
            assert res["observation"]["state"]["tick"] == 1
            assert abs(res["reward"] - (-0.1)) < 1e-9
        # Rewards are fixed at reset and persist for subsequent steps.
        assert abs(ws_step(ws1, 1)["reward"] - (-0.1)) < 1e-9
        assert ws_state(ws2)["step_count"] == 1


@pytest.mark.parametrize("game,action", [("snake", 9), ("tetris", 4)])
def test_invalid_action_returns_openenv_error(game, action):
    with client.websocket_connect(f"/api/openenv/{game}/ws") as ws:
        ws_reset(ws, seed=1, obs_mode="state")
        response = ws_message(ws, "step", {"value": action})
        assert response["type"] == "error", response


def test_adapter_rejects_invalid_state_and_internal_batch_mismatch():
    adapter = registry.resolve("snake")
    s = adapter.new_state(1)
    with pytest.raises(WorkerError, match="matching actions"):
        adapter.step_batch([s], [1, 0])
    # Game state belongs to the session, so invalid states are engine-only tests.
    with pytest.raises(ValueError):
        adapter.validate_state(dict(s, body=[[1, 1]]))


def test_unknown_reward_key_returns_openenv_error():
    with client.websocket_connect("/api/openenv/tetris/ws") as ws:
        response = ws_message(ws, "reset", {
            "seed": 1, "obs_mode": "state", "rewards": {"food": 1.0}})
        assert response["type"] == "error", response


def test_snake_ai_action():
    # 13 G3：载荷统一为 {state, strategy?, owner?}（UGCAIRequest）
    with client.websocket_connect("/api/openenv/snake/ws") as ws:
        s = ws_reset(ws, seed=0, obs_mode="state")["observation"]["state"]
    r = client.post("/api/snake/ai/action", json={"state": s})
    assert r.status_code == 200
    data = r.json()
    assert data["action"] in (0, 1, 2)
    assert len(data["q"]) == 3
    assert data["action_name"] in ("left", "straight", "right")


def test_tetris_ai_action():
    with client.websocket_connect("/api/openenv/tetris/ws") as ws:
        s = ws_reset(ws, seed=5, obs_mode="state")["observation"]["state"]
    r = client.post("/api/tetris/ai/action", json={"state": s})
    assert r.status_code == 200
    data = r.json()
    assert data["action"] in (0, 1, 2, 3)
    assert data["action_name"] in ("left", "right", "rotate", "hard_drop")


def test_scores_claimed_from_pve_match():
    """分数只能凭服务端对局领取；客户端自报的数字被忽略。"""
    headers = _user_headers()
    match_id, score = _play_snake_to_end(headers)
    r = client.post("/api/snake/scores",
                    json={"match_id": match_id, "score": 9999,
                          "name": "测试玩家"}, headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["score"] == score and body["match_id"] == match_id
    items = client.get("/api/snake/scores?limit=5").json()["items"]
    assert any(it["score"] == score and it["name"] == "测试玩家"
               for it in items)
    # 同一场对局只能上榜一次
    r = client.post("/api/snake/scores", json={"match_id": match_id},
                    headers=headers)
    assert r.status_code == 400, r.text


def test_scores_reject_unknown_foreign_and_unauthenticated():
    headers = _user_headers()
    assert client.post("/api/snake/scores", json={"match_id": 999999},
                       headers=headers).status_code == 404
    other = _user_headers()
    match_id, _ = _play_snake_to_end(other)
    r = client.post("/api/snake/scores", json={"match_id": match_id},
                    headers=headers)
    assert r.status_code == 403, r.text  # 别人的对局
    api_limits._hits.clear()
    r = client.post("/api/snake/scores", json={"match_id": match_id})
    assert r.status_code == 401, r.text  # 未登录


def test_scores_rate_limit_per_user():
    """docs/design/02: 登录用户 5 req/s（独立 bucket）。"""
    h1 = _user_headers()
    api_limits._hits.clear()
    missing = 999_999_999
    for _ in range(5):
        r = client.post("/api/snake/scores", json={"match_id": missing},
                        headers=h1)
        assert r.status_code == 404, r.text  # 额度耗尽前先走校验
    assert client.post("/api/snake/scores", json={"match_id": missing},
                       headers=h1).status_code == 429
    # 另一个账号有独立额度
    h2 = _user_headers()
    assert client.post("/api/snake/scores", json={"match_id": missing},
                       headers=h2).status_code == 404
    api_limits._hits.clear()


def test_ai_action_rate_limit_tiers():
    """docs/design/02: ai/action 游客/IP 30 req/s，登录用户 60 req/s。"""
    with client.websocket_connect("/api/openenv/snake/ws") as ws:
        s = ws_reset(ws, seed=0, obs_mode="state")["observation"]["state"]
    api_limits._hits.clear()
    for _ in range(30):
        r = client.post("/api/snake/ai/action", json={"state": s})
        assert r.status_code == 200, r.text
    assert client.post("/api/snake/ai/action",
                       json={"state": s}).status_code == 429
    # 登录用户额度更高（按 user_id 计数）
    headers = _user_headers()
    api_limits._hits.clear()
    for _ in range(31):
        r = client.post("/api/snake/ai/action", json={"state": s},
                        headers=headers)
        assert r.status_code == 200, r.text
    api_limits._hits.clear()


def test_lobby_and_game_pages_served():
    # "/" is the React SPA when web/dist is built, else a build hint page
    r = client.get("/")
    assert r.status_code == 200
    assert 'id="root"' in r.text or "frontend not built" in r.text
    # every game page is served by the SPA (built) or a hint (dev)
    for game in ("microrts", "snake", "tetris"):
        r = client.get(f"/games/{game}/")
        assert r.status_code == 200
        assert 'id="root"' in r.text or "frontend not built" in r.text
    # 13 G3：/games/{slug} 统一路由对未知 slug 也返回 SPA（前端显示「游戏不存在」）
    r = client.get("/games/nope/")
    assert r.status_code == 200


def test_microrts_openenv_single_agent():
    info = environment_info(client, "microrts")
    assert info["game"] == "microrts" and info["grid"] == [16, 16]
    assert info["two_player"] is True
    assert "external" in info["opponents"]
    assert info["max_concurrent_envs"] == 64

    # single-agent mode: p0 vs builtin light_rush
    with client.websocket_connect("/api/openenv/microrts/ws") as ws:
        data = ws_reset(ws, seed=42, obs_mode="grid", include_state=True,
                        options={"opponent": "light_rush"})
        obs = data["observation"]
        s = obs["state"]
        assert s["opponent"] == "light_rush" and len(s["units"]) == 2
        assert obs["type"] == "tensor" and obs["shape"] == [6, 16, 16]
        assert len(obs["data"]) == 6 and len(obs["data"][0]) == 16
        assert obs["metadata"]["environment"] == info

        base0 = s["units"][0]["id"]
        res = ws_step(ws, [[base0, 0]])  # p0 waits; AI plays on
        assert res["observation"]["state"]["tick"] == 1
        assert "reward" in res and "done" in res


def test_microrts_openenv_two_agent():
    with client.websocket_connect("/api/openenv/microrts/ws") as ws:
        data = ws_reset(ws, seed=7, obs_mode="state",
                        options={"opponent": "external"})
        s = data["observation"]["state"]
        ids = [u["id"] for u in s["units"]]
        action = {"p0": [[ids[0], 0]], "p1": [[ids[1], 0]]}
        res = ws_step(ws, action)
        assert res["observation"]["state"]["tick"] == 1
        # Wrong action shape for the mode -> official error frame.
        response = ws_message(ws, "step", {"value": [[ids[0], 0]]})
        assert response["type"] == "error", response
        # Invalid command -> official error frame.
        response = ws_message(ws, "step", {
            "value": {"p0": [[ids[0], 9, 1]], "p1": []}})
        assert response["type"] == "error", response


def test_microrts_ai_action():
    with client.websocket_connect("/api/openenv/microrts/ws") as ws:
        data = ws_reset(ws, seed=3, obs_mode="state",
                        options={"opponent": "worker_rush"})
        s = data["observation"]["state"]
    r = client.post("/api/microrts/ai/action", json={"state": s})
    assert r.status_code == 200
    data = r.json()
    assert data["strategy"] == "worker_rush"
    assert isinstance(data["action"], list)  # composite commands

    r = client.post("/api/microrts/ai/action",
                    json={"state": s, "strategy": "light_rush"})
    assert r.status_code == 200 and r.json()["strategy"] == "light_rush"


@pytest.mark.parametrize("game", ["snake", "tetris", "microrts"])
@pytest.mark.parametrize("method,operation,payload", [
    ("GET", "info", None),
    ("POST", "new_batch", {"seeds": [0]}),
    ("POST", "step", {"states": [], "actions": []}),
])
def test_native_environment_routes_removed(game, method, operation, payload):
    # Deliberate removal, not a native compatibility surface.
    r = client.request(method, f"/api/{game}/env/{operation}", json=payload)
    assert r.status_code == 404, r.text


def test_openapi_docs():
    r = client.get("/openapi.json")
    assert r.status_code == 200
    assert all("/env/" not in path for path in r.json()["paths"])
    assert client.get("/docs").status_code == 200
