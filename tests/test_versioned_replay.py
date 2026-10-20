"""Version upgrades must not change running sessions or historical replay."""
import io
from pathlib import Path
import sys
import uuid
import zipfile

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import main
import auth
import matches
import registry
import sessions
import ugc
import ugc_runner
from openenv_helpers import ws_message, ws_reset, ws_state, ws_step


def package(slug, version, increment):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("game.yaml", f'''slug: {slug}
title: Version counter
description: Reproducibility acceptance fixture
version: {version}
board:
  width: 1
  height: 1
  palette:
    empty: {{glyph: "·"}}
''')
        # Deliberately omit seed from state: the session owns the original seed.
        z.writestr("__init__.py", f'''
class Counter:
    score_bounds = (0, 100)
    def info(self):
        return {{"actions": {{"0": "advance"}}, "default_rewards": {{}},
                 "obs_modes": ["v{increment}"], "obs_shape": [1]}}
    def new_state(self, seed, options=None):
        return {{"n": (options or {{}}).get("start", 0), "tick": 0, "done": False}}
    def validate_state(self, state):
        if not isinstance(state.get("n"), int): raise ValueError("bad state")
    def validate_action(self, action, state):
        if action != 0: raise ValueError("bad action")
    def sample_action(self, state): return 0
    def step_state(self, state, action, rewards=None):
        n = state["n"] + {increment}
        return dict(state, n=n, tick=state["tick"]+1, done=n>=3)
    def obs(self, state, mode=None): return [state["n"]]
def get_adapter(): return Counter()
''')
    return buf.getvalue()


def test_upgrade_session_replay_and_archived_metadata():
    client = TestClient(main.app)
    slug = "replay-" + uuid.uuid4().hex[:8]
    user, _ = auth.register_user("replay_" + uuid.uuid4().hex[:8], "local-test-password")
    try:
        game, version = ugc.seed_game(user["id"], package(slug, "1.0.0", 1))
        ugc._register_game(game, version)
        session = sessions.create_session(slug, user, 0, None)
        assert sessions.step_session(session, 0)["n"] == 1
        game, version2 = ugc.seed_game(user["id"], package(slug, "2.0.0", 10))
        ugc._register_game(game, version2)
        assert registry.resolve(slug).step_state({"n": 0, "tick": 0}, 0)["n"] == 10
        assert sessions.step_session(session, 0)["n"] == 2
        original_final = sessions.step_session(session, 0)
        assert original_final["n"] == 3
        assert sessions.session_replay(session)["seed"] == 0
        match_id = matches.record_pve_finish(session)
        replay = client.get(f"/api/v1/matches/{match_id}/replay").json()["replay"]
        assert replay["seed"] == 0 and replay["game_version"] == "1.0.0"

        # Drop in-memory workers/registry and resolve the old package from SQLite.
        ugc_runner.drop_worker(slug)
        registry.unregister(slug)
        ugc._register_game(game, version2)
        endpoint = f"/api/openenv/{slug}"
        with client.websocket_connect(endpoint + "/ws") as ws:
            current = ws_state(ws)
            assert current["game_state"] is None
            assert current["environment"]["obs_modes"] == ["v10"]
            result = ws_reset(ws, seed=replay["seed"], version="1.0.0",
                              options=replay["options"], obs_mode="state")
            old_info = result["observation"]["metadata"]["environment"]
            assert old_info["obs_modes"] == ["v1"]
            assert old_info["version"] == old_info["meta"]["version"] == "1.0.0"
            state = result["observation"]["state"]
            for index, move in enumerate(replay["moves"], 1):
                state = ws_step(ws, move["action"])["observation"]["state"]
                assert state["n"] == index  # never switch to current increment=10
            assert state == original_final
            snapshot = ws_state(ws)
            assert snapshot["game_state"] == original_final
            assert snapshot["environment"] == old_info
            result = ws_reset(ws, seed=0, version="1.0.0",
                              options={"start": 7}, obs_mode="v1", include_state=True)
            assert result["observation"]["data"] == [7]
            assert result["observation"]["state"]["n"] == 7
            error = ws_message(ws, "reset", {"seed": 0, "version": "9.0.0"})
            assert error["type"] == "error", error
            ugc.unpublish(game["id"], user["id"])
            error = ws_message(ws, "step", {"value": 0})
            assert error["type"] == "error", error
        assert client.get(endpoint + "/schema").status_code == 404
    finally:
        registry.unregister(slug)
        ugc_runner.drop_worker(slug)


def test_boot_keeps_newer_published_package(tmp_path, monkeypatch):
    import platform_api
    slug = "boot-" + uuid.uuid4().hex[:8]
    bundled = tmp_path / "packaged-games" / slug
    bundled.mkdir(parents=True)
    with zipfile.ZipFile(io.BytesIO(package(slug, "1.0.0", 1))) as z:
        z.extractall(bundled)
    monkeypatch.setattr(main, "BASE_DIR", tmp_path / "backend")
    monkeypatch.setattr(platform_api, "EXPECTED_GAMES", set())
    game, version = ugc.seed_game(auth.official_author_id(), package(slug, "2.0.0", 10))
    try:
        main._seed_bundled_games()
        assert ugc.active_version(game["id"])["id"] == version["id"]
        ugc._register_game(game, version)
        assert platform_api.ready()["games"] == [slug]
        assert registry.resolve(slug).step_state({"n": 0, "tick": 0}, 0)["n"] == 10
    finally:
        registry.unregister(slug)
        ugc_runner.drop_worker(slug)
