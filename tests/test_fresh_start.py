"""Acceptance: no admin credentials, empty data dir, real server and restart."""
import sqlite3

import requests
from openenv.core import GenericEnvClient

from live_server import live_server


def test_fresh_install_and_restart_without_admin(tmp_path):
    game_ids = {"snake", "tetris", "microrts"}
    with live_server(admin=False, data_dir=tmp_path) as base:
        response = requests.get(base + "/api/ready", timeout=5)
        assert response.status_code == 200, response.text
        assert set(response.json()["games"]) == game_ids
        catalog = requests.get(base + "/api/games", timeout=5).json()["games"]
        assert {g["id"] for g in catalog} == game_ids
        assert all(g["author"] == "官方" for g in catalog)
        user = requests.post(base + "/api/v1/auth/register", json={
            "username": "first_user", "password": "local-test-password"}, timeout=5)
        assert user.status_code == 200
        assert user.json()["user"]["role"] == "user"
        for game in game_ids:
            with GenericEnvClient(base_url=base + f"/api/openenv/{game}") as env:
                info = env.state()["environment"]
                assert info["game"] == game and info["version"]
                for seed in (0, 1):
                    result = env.reset(seed=seed, obs_mode="state")
                    assert result.observation["type"] == "state"
                    assert result.observation["state"]["tick"] == 0
                    action = 1 if game == "snake" else 3 if game == "tetris" else []
                    result = env.step({"value": action})
                    assert result.observation["state"]["tick"] == 1
                    assert env.state()["game_state"] == result.observation["state"]
        with sqlite3.connect(tmp_path / "scores.db") as conn:
            versions = conn.execute("SELECT id,version,package_path FROM ugc_versions ORDER BY id").fetchall()
            assert len(versions) == 3
            assert conn.execute("SELECT count(*) FROM users WHERE role='admin'").fetchone()[0] == 0
            author = conn.execute("SELECT password_hash,role,status FROM users WHERE username='system:official'").fetchone()
            assert author == ("!", "system", "disabled")
    with live_server(admin=False, data_dir=tmp_path) as base:
        assert requests.get(base + "/api/ready", timeout=5).status_code == 200
        with sqlite3.connect(tmp_path / "scores.db") as conn:
            assert conn.execute("SELECT id,version,package_path FROM ugc_versions ORDER BY id").fetchall() == versions
        response = requests.post(base + "/api/v1/auth/login", json={
            "username": "first_user", "password": "local-test-password"}, timeout=5)
        assert response.status_code == 200


def test_readiness_detects_missing_game():
    import main
    import registry
    from fastapi.testclient import TestClient
    adapter = registry.GAMES.pop("snake")
    try:
        assert TestClient(main.app).get("/api/ready").status_code == 503
    finally:
        registry.GAMES["snake"] = adapter
