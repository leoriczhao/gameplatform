"""Local training (18): package distribution, in-process runtime parity with
the server's OpenEnv sessions, export from the package contract, evaluation."""
import hashlib
import io
import json
import sys
import zipfile

import numpy as np
import pytest
import requests

from live_server import ROOT, live_server

sys.path.insert(0, str(ROOT / "sdk"))
from gameplatform import (LocalGame, LocalVecEnv, RemoteVecEnv, evaluate,  # noqa: E402
                          export_onnx, fetch_package, load_game, parity_check)

ADMIN = ("smokeadmin", "smoke-local-password")

COUNTER_YAML = """slug: {slug}
title: 计数器
description: 本地训练测试用计数器
version: 1.0.0
local_training: {local}
board:
  width: 4
  height: 4
  palette:
    empty: {{ glyph: "·" }}
    full:  {{ glyph: "■" }}
"""

COUNTER_CODE = '''
class Counter:
    score_bounds = (0, 100)
    def info(self):
        return {"grid": [4, 4], "action_space": "discrete(2)", "actions": {"0": "stay", "1": "add"}}
    def new_state(self, seed, options=None):
        return {"tick": 0, "done": False, "winner": None, "cause": None, "seed": seed,
                "n": 0, "pair": (seed % 3, 1), "board": [["empty"] * 4 for _ in range(4)]}
    def validate_state(self, state):
        pass
    def validate_action(self, action, state):
        if action not in (0, 1):
            raise ValueError("0/1 required")
    def step_state(self, state, action):
        s = dict(state, n=state["n"] + action, tick=state["tick"] + 1, reward=float(action))
        if s["n"] >= 5:
            s.update(done=True, winner=0, cause="done")
        return s
    def sample_action(self, state):
        return 1
def get_adapter():
    return Counter()
'''


@pytest.fixture(scope="module")
def base_url():
    with live_server() as base:
        yield base


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setenv("GAMEPLATFORM_CACHE", str(tmp_path / "cache"))
    return tmp_path / "cache"


def _publish_counter(base, slug, local):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("game.yaml", COUNTER_YAML.format(slug=slug, local=local))
        zf.writestr("__init__.py", COUNTER_CODE)
    author = requests.post(base + "/api/v1/auth/register",
                           json={"username": f"author_{slug}".replace("-", "_"),
                                 "password": "password123"}).json()
    r = requests.post(base + "/api/v1/ugc/games",
                      files={"file": (f"{slug}.zip", buf.getvalue(), "application/zip")},
                      data={"changelog": "init"},
                      headers={"Authorization": f"Bearer {author['token']}"})
    assert r.status_code == 200, r.text
    gid = r.json()["game"]["id"]
    assert requests.post(f"{base}/api/v1/ugc/games/{gid}/submit",
                         headers={"Authorization": f"Bearer {author['token']}"}).ok
    admin = requests.post(base + "/api/v1/auth/login",
                          json={"username": ADMIN[0], "password": ADMIN[1]}).json()
    r = requests.post(f"{base}/api/v1/admin/ugc/{gid}/approve",
                      headers={"Authorization": f"Bearer {admin['token']}"})
    assert r.status_code == 200, r.text


# ---------------------------------------------------------------- server side

@pytest.mark.parametrize("game", ["snake", "tetris", "microrts"])
def test_official_package_manifest_and_deterministic_zip(base_url, game):
    manifest = requests.get(f"{base_url}/api/v1/games/{game}/package").json()
    assert manifest["official"] is True and manifest["slug"] == game
    first = requests.get(base_url + manifest["url"])
    second = requests.get(base_url + manifest["url"])
    assert first.status_code == 200 and first.content == second.content
    assert hashlib.sha256(first.content).hexdigest() == manifest["sha256"]
    assert len(first.content) == manifest["size"]
    assert first.headers["etag"] == f'"{manifest["sha256"]}"'
    assert "immutable" in first.headers["cache-control"]
    names = zipfile.ZipFile(io.BytesIO(first.content)).namelist()
    assert "game.yaml" in names and "__init__.py" in names
    assert not any("__pycache__" in n or n.endswith(".pyc") for n in names)
    pinned = requests.get(f"{base_url}/api/v1/games/{game}/package",
                          params={"version": manifest["version"]}).json()
    assert pinned["sha256"] == manifest["sha256"]


def test_package_errors(base_url):
    assert requests.get(f"{base_url}/api/v1/games/no-such-game/package").status_code == 404
    assert requests.get(f"{base_url}/api/v1/games/snake/package",
                        params={"version": "9.9.9"}).status_code == 404
    assert requests.get(f"{base_url}/api/v1/games/snake/package/9.9.9.zip").status_code == 404


def test_ugc_distribution_requires_author_opt_in(base_url, cache):
    _publish_counter(base_url, "counter-closed", "false")
    r = requests.get(f"{base_url}/api/v1/games/counter-closed/package")
    assert r.status_code == 403 and "local_training" in r.json()["detail"]
    assert requests.get(f"{base_url}/api/v1/games/counter-closed/package/1.0.0.zip").status_code == 403

    _publish_counter(base_url, "counter-open", "true")
    manifest = requests.get(f"{base_url}/api/v1/games/counter-open/package").json()
    assert manifest["official"] is False and manifest["meta"]["local_training"] is True
    with pytest.raises(PermissionError, match="trust_remote_code"):
        fetch_package("counter-open", base_url=base_url)
    envs = LocalVecEnv("counter-open", n=2, base_url=base_url, trust_remote_code=True)
    # the sandbox's JSON boundary: the package's tuple arrives as a list
    assert envs.states[0]["pair"] == [0, 1]
    _, rewards, dones, _ = envs.step([1, 0])
    assert rewards.tolist() == [1.0, 0.0] and not dones.any()
    assert parity_check("counter-open", base_url=base_url, steps=10,
                        trust_remote_code=True)["ok"]


# ---------------------------------------------------------------- sdk side

@pytest.mark.parametrize("game,options", [("snake", None), ("tetris", None),
                                          ("microrts", None),
                                          ("microrts", {"opponent": "light_rush"})])
def test_local_trajectory_matches_remote(base_url, cache, game, options):
    result = parity_check(game, base_url=base_url, seed=11, steps=120, options=options)
    assert result["ok"], result
    assert result["steps"] > 0


@pytest.mark.parametrize("mode", ["grid", "rotwin", "features", "state"])
def test_local_observations_rewards_and_autoreset_match_remote(base_url, cache, mode):
    rewards = {"food": 5.0, "step": -0.5, "death": -3.0}
    local = LocalVecEnv("snake", n=3, base_url=base_url, seed=5, obs_mode=mode, rewards=rewards)
    with RemoteVecEnv("snake", n=3, base_url=base_url, seed=5, obs_mode=mode,
                      rewards=rewards) as remote:
        assert local.num_actions == remote.num_actions == 3
        assert local.game_version == remote.game_version
        for t in range(40):
            if mode == "state":
                assert local._last_obs == remote._last_obs
            else:
                np.testing.assert_array_equal(local._last_obs, remote._last_obs)
            actions = [(t + i) % 3 for i in range(3)]
            lo, lr, ld, li = local.step(actions)
            ro, rr, rd, ri = remote.step(actions)
            np.testing.assert_array_equal(lr, rr)
            np.testing.assert_array_equal(ld, rd)
            assert [i["state"] for i in li] == [i["state"] for i in ri]
            for i in np.flatnonzero(ld):
                a, b = local.terminal_obs(li[i]), remote.terminal_obs(ri[i])
                if mode == "state":
                    assert a == b
                else:
                    np.testing.assert_array_equal(a, b)


def test_cache_is_reused_offline_and_verified(base_url, cache):
    path = fetch_package("snake", base_url=base_url)
    version = json.loads((path / ".manifest.json").read_text())["version"]
    assert fetch_package("snake", version, base_url="http://127.0.0.1:9") == path
    with pytest.raises(RuntimeError, match="unavailable"):
        fetch_package("no-such-game", base_url=base_url)


def test_package_directory_loads_without_server():
    game = load_game(str(ROOT / "packaged-games" / "snake"))
    assert isinstance(game, LocalGame) and game.slug == "snake"
    state = game.new_state(3)
    assert state["seed"] == 3 and isinstance(state["body"][0], list)


def test_export_uses_package_contract_and_local_evaluate(base_url, cache, tmp_path):
    torch = pytest.importorskip("torch")
    torch.manual_seed(0)
    envs = LocalVecEnv("snake", n=1, base_url=base_url, obs_mode="rotwin")
    net = torch.nn.Sequential(torch.nn.Linear(1334, 3))
    path = tmp_path / "snake.onnx"
    assert export_onnx(net, envs.runtime, str(path)) == "game.snake"
    first = evaluate(path, envs.runtime, episodes=3, seed=7)
    assert first == evaluate(path, envs.runtime, episodes=3, seed=7)  # same seeds, same games
    assert first["episodes"] == 3 and first["seeds"] == [7, 9] and "win_rate" not in first

    rts = load_game("microrts", base_url=base_url)
    big = torch.nn.Sequential(torch.nn.Linear(1546, 140))
    rts_path = tmp_path / "microrts.onnx"
    assert export_onnx(big, "microrts", str(rts_path), base_url=base_url) == "game.microrts"
    metrics = evaluate(rts_path, rts, episodes=1, seed=3)
    assert metrics["opponent"] == rts.meta["default_opponent"] and "win_rate" in metrics


def test_parity_check_reports_first_divergent_step(base_url, cache, monkeypatch):
    original = LocalGame.step_state

    def drift(self, state, action, rewards=None):
        nxt = original(self, state, action, rewards)
        return dict(nxt, score=nxt["score"] + 1) if nxt["tick"] == 5 else nxt

    monkeypatch.setattr(LocalGame, "step_state", drift)
    result = parity_check("snake", base_url=base_url, seed=1, steps=50)
    assert result["ok"] is False and result["mismatch_at"] == 5
