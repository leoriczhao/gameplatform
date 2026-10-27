"""gamekernel (19): call semantics, episode rules, model protocol, loader."""
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sdk"))

from gamekernel import calls, episode, loader, models  # noqa: E402


class OldStep:
    """A legacy adapter: step_state without rewards, no ai_action, no obs."""
    def info(self):
        return {"actions": {"0": "a", "1": "b"}, "default_rewards": {"hit": 1.0}}

    def new_state(self, seed, options=None):
        return {"tick": 0, "seed": seed, "pair": (1, 2), "done": False}

    def step_state(self, state, action):
        done = state["tick"] + 1 >= 3
        return {**state, "tick": state["tick"] + 1, "reward": "bad" if action == 1 else 1, "done": done}

    def validate_state(self, state):
        pass

    def validate_action(self, action, state=None):
        if action not in (0, 1):
            raise ValueError("bad action")

    def opponent_action(self, state, config):
        return config.get("strategy", "none")

    def model_inputs(self, state):            # no owner argument
        return [[0.0, 1.0]]

    def model_decode(self, outputs, state):   # no owner argument
        return int(np.argmax(outputs[0]))


def test_call_fallbacks_and_json_boundary():
    raw = calls.GameCalls(OldStep())
    wired = calls.GameCalls(OldStep(), wire_outputs=True)
    assert raw.new_state(1)["pair"] == (1, 2)
    assert wired.new_state(1)["pair"] == [1, 2]
    state = wired.new_state(1)
    assert wired.step_state(state, 0, {"hit": 2.0})["tick"] == 1   # TypeError fallback
    assert wired.ai_action({"state": state, "strategy": "s"}) == {"action": "s"}
    assert wired.model_inputs(state, owner=1) == [[0.0, 1.0]]
    assert wired.model_decode([[0.2, 0.9]], state, owner=1) == 1
    assert wired.obs(state) is None and wired.obs_array(state) is None
    assert wired.score_bounds() == [0, 1_000_000]
    with pytest.raises(ValueError, match="1..256"):
        raw.step_batch([], [])
    batch = raw.dispatch("step_batch", {"states": [state], "actions": [1]})
    assert batch[0]["state"]["tick"] == 1
    with pytest.raises(ValueError, match="unknown op"):
        raw.dispatch("nope", {})


def test_episode_rules():
    game = calls.GameCalls(OldStep(), wire_outputs=True)
    info = game.info()
    with pytest.raises(ValueError, match="unknown reward key"):
        episode.Episode(game, info, {"miss": 1})
    with pytest.raises(ValueError, match="out of range"):
        episode.Episode(game, info, {"hit": 1e6})
    ep = episode.Episode(game, info, {"hit": 3})
    assert ep.rewards == {"hit": 3.0}
    with pytest.raises(ValueError, match="reset first"):
        ep.step(0)
    for bad in (-1, True, 1.5):
        with pytest.raises(ValueError, match="non-negative"):
            ep.reset(bad)
    with pytest.raises(ValueError, match="options"):
        ep.reset(0, options=[1])
    ep.reset(4)
    with pytest.raises(ValueError, match="bad action"):
        ep.step(7)
    assert ep.step(0)[1:] == (1.0, False)
    assert ep.step(1)[1:] == (None, False)        # non-numeric reward -> None
    assert ep.step(0)[2] is True and ep.done and ep.step_count == 3


def test_obs_mode_resolution_and_schemas():
    info = {"obs_modes": ["grid", "rotwin"], "obs_shape": [2, 3],
            "actions": {"0": "x", "1": "y"}}
    assert episode.resolve_obs_mode(info, None) == "grid"
    assert episode.resolve_obs_mode(info, "state") is None
    assert episode.resolve_obs_mode(info, "rotwin") == "rotwin"
    with pytest.raises(ValueError, match="unknown obs_mode"):
        episode.resolve_obs_mode(info, "pixels")
    schemas = episode.environment_schemas(info)
    assert schemas["action"]["enum"] == [0, 1]
    assert schemas["observations"]["grid"]["x-shape"] == [2, 3]


def test_model_protocol_and_evaluate():
    game = calls.GameCalls(OldStep(), wire_outputs=True)
    composite = models.contract_of({"slug": "old", "contract": {
        "in_shape": [1, 2], "out_shape": [1, 2], "protocol": "composite"}})
    assert composite["name"] == "game.old" and composite["input"] == (1, 2)
    assert models.contract_of({"slug": "x"}) is None
    run = lambda x: np.asarray([[0.1, 0.9]], dtype=np.float32)  # noqa: E731
    assert models.model_action(game, composite, run, game.new_state(0), owner=1) == 1
    meta = {"opponents": ["rush"], "pvp": {"options": None}}
    seen = []

    def act(state, owner):
        seen.append(state["seed"])
        return 0
    first = models.evaluate(game, meta, act, [5, 6])
    assert first["opponent"] == "rush" and first["episodes"] == 2 and "win_rate" in first
    assert models.evaluate(game, meta, act, [5, 6]) == first
    assert sorted(set(seen)) == [5, 6]


def test_loader_requires_get_adapter(tmp_path):
    (tmp_path / "__init__.py").write_text("X = 1\n")
    with pytest.raises(loader.PackageError, match="get_adapter"):
        loader.load_package(tmp_path, module_name="_kernel_test_pkg")
    adapter = loader.load_package(ROOT / "packaged-games" / "snake", "_kernel_test_snake")
    assert adapter.new_state(1)["seed"] == 1
