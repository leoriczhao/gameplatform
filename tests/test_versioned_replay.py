"""Version upgrades must not change archived v1 replay rows (design 17 M4).

The v1 replay rebuild test is gone with the v1 play sessions; what survives is
the boot path: a newer published package must never replace a newer archived
version at startup.
"""
import io
from pathlib import Path
import sys
import uuid
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import main
import auth
import registry
import ugc
import ugc_runner


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
