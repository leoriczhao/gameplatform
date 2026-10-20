"""Batching must preserve scalar trajectories and cross IPC once per batch."""
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import main
import registry
from ugc_runner import WorkerError
from openenv_helpers import environment_info


@pytest.mark.parametrize("game", ["snake", "tetris", "microrts"])
def test_batch_matches_scalar_and_single_rpc(game, monkeypatch):
    adapter = registry.GAMES[game]
    mode = adapter.info()["obs_modes"][0]
    seeds = list(range(16))
    expected_new = [{"state": adapter.new_state(seed)} for seed in seeds]
    for item in expected_new:
        item["obs"] = adapter.obs(item["state"], mode)
    assert adapter.new_batch(seeds, obs_mode=mode) == expected_new
    states = [r["state"] for r in expected_new]
    actions = [adapter.sample_action(s) for s in states]
    expected = []
    for s, a in zip(states, actions):
        nxt = adapter.step_state(s, a, adapter.info()["default_rewards"])
        expected.append({"state": nxt, "reward": nxt.get("reward", 0.),
                         "done": nxt.get("done", False), "obs": adapter.obs(nxt, mode)})
    calls = []
    worker = adapter._worker()
    original = worker.request
    def count(op, **kwargs):
        calls.append(op)
        return original(op, **kwargs)
    monkeypatch.setattr(worker, "request", count)
    results = adapter.step_batch(states, actions, adapter.info()["default_rewards"], mode)
    assert calls == ["step_batch"]
    for actual, wanted in zip(results, expected):
        assert {k: actual[k] for k in wanted} == wanted
    calls.clear()
    assert adapter.new_batch(seeds, obs_mode=mode) == expected_new
    assert calls == ["new_batch"]


@pytest.mark.parametrize("game,size", [("microrts", 128), ("snake", 256)])
def test_internal_batches_support_declared_sizes(game, size):
    # Batch IPC remains an engine facility, not a public HTTP protocol.
    adapter = registry.GAMES[game]
    assert adapter.info()["max_batch"] == size
    states = [item["state"] for item in adapter.new_batch(list(range(size)))]
    assert len(states) == size
    actions = [adapter.sample_action(state) for state in states]
    assert len(adapter.step_batch(states, actions)) == size
    # Network clients use one persistent WS per environment instead.
    info = environment_info(TestClient(main.app), game)
    assert info["max_concurrent_envs"] == 64


def test_internal_batch_bounds_and_invalid_input():
    adapter = registry.GAMES["snake"]
    states = [item["state"] for item in adapter.new_batch([0, 1])]
    for batch, actions in (([], []), ([states[0]] * 257, [1] * 257),
                           (states, [1])):
        with pytest.raises(WorkerError, match="batch requires"):
            adapter.step_batch(batch, actions)
    with pytest.raises(WorkerError):
        adapter.step_batch(states, [1, 999])
