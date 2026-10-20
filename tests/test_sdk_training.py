"""Official OpenEnv WS, NumPy actions, torch updates and ONNX upload/play."""
from copy import deepcopy
import os
from types import SimpleNamespace
import subprocess
import sys

import numpy as np
import pytest
import requests
from openenv.core import GenericEnvClient
from openenv.core.client_types import StepResult

from live_server import ROOT, live_server

sys.path.insert(0, str(ROOT / "sdk"))
from gameplatform import PlatformClient, RemoteVecEnv, export_onnx
from gameplatform.gym import PlatformRemoteEnv, PlatformRemoteVecEnv


@pytest.fixture(scope="module")
def base_url():
    with live_server() as base:
        yield base


@pytest.mark.parametrize("game", ["snake", "tetris"])
def test_bundled_dqn_script_updates_weights(base_url, tmp_path, game):
    import torch
    import importlib.util
    script = ROOT / "training" / f"{game}_dqn.py"
    output = tmp_path / "weights.pt"
    env = {**os.environ, "PYTHONPATH": str(ROOT / "sdk"),
           "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "CUDA_VISIBLE_DEVICES": ""}
    run = subprocess.run([sys.executable, str(script), "--base-url", base_url,
                          "--envs", "2", "--episodes", "2", "--batch-size", "4",
                          "--eval-interval", "100000", "--seed", "0", "--save", str(output)],
                         env=env, capture_output=True, text=True, timeout=90)
    assert run.returncode == 0, run.stdout + run.stderr
    weights = torch.load(output, map_location="cpu", weights_only=True)
    spec = importlib.util.spec_from_file_location("dqn_script", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    dim = weights["net.0.weight"].shape[1]
    torch.manual_seed(0)
    initial = module.MLP(dim).state_dict()
    assert all(torch.isfinite(v).all() for v in weights.values())
    assert any(not torch.equal(weights[k], initial[k]) for k in weights)


def test_train_export_upload_and_model_play(base_url, tmp_path):
    import torch
    torch.set_num_threads(1)
    torch.manual_seed(7)
    remote = RemoteVecEnv(game="tetris", n=4, obs_mode="grid", base_url=base_url)
    net = torch.nn.Sequential(torch.nn.Flatten(), torch.nn.Linear(400, 4))
    optim = torch.optim.Adam(net.parameters(), lr=.001)
    before = net[1].weight.detach().clone()
    obs = remote._last_obs
    try:
        for _ in range(8):
            x = torch.from_numpy(obs)
            q = net(x)
            actions = q.detach().argmax(1).numpy()
            obs, reward, done, _ = remote.step(actions)
            with torch.no_grad():
                target = torch.from_numpy(reward) + .97 * net(torch.from_numpy(obs)).max(1).values * torch.from_numpy(~done)
            loss = torch.nn.functional.smooth_l1_loss(q.gather(1, torch.from_numpy(actions)[:, None]).squeeze(1), target)
            optim.zero_grad(); loss.backward(); optim.step()
        assert torch.isfinite(loss)
        assert not torch.equal(net[1].weight, before)
        path = tmp_path / "trained.onnx"
        export_onnx(net, "tetris", str(path))
        client = PlatformClient(base_url)
        client.register("training_smoke", "local-smoke-password")
        model = client.upload_model(str(path), "tetris", "smoke-trained")
        response = client._req("POST", "/api/v1/tetris/play/sessions", json={
            "seed": 7, "controller": {"type": "model", "model_id": model["id"]}})
        sid = response["session"]["id"]
        result = client._req("POST", f"/api/v1/tetris/play/sessions/{sid}/actions", json={"actions": None})
        assert "state" in result
    finally:
        remote.close()


def test_gym_seed_and_terminal_observation(base_url):
    env = PlatformRemoteEnv(game="snake", obs_mode="grid", base_url=base_url)
    try:
        first, info = env.reset(seed=0)
        assert info["state"]["seed"] == 0
        np.testing.assert_array_equal(first, env.reset(seed=0)[0])
        for _ in range(30):
            obs, _, done, _, info = env.step(np.int64(1))
            if done:
                np.testing.assert_array_equal(obs, env._remote.terminal_obs(info))
                assert env._remote.states[0]["done"]
                with pytest.raises(RuntimeError, match="call reset"):
                    env.step(1)
                _, reset_info = env.reset()
                assert reset_info["state"]["seed"] == 100003
                assert not reset_info["state"]["done"]
                break
        else:
            pytest.fail("straight-moving snake should hit wall")
    finally:
        env.close()


def test_vector_same_step_terminal_contract(base_url):
    env = PlatformRemoteVecEnv(game="snake", n=2, obs_mode="grid", base_url=base_url)
    try:
        env.reset(seed=[0, 1])
        assert env.metadata["autoreset_mode"].value == "SameStep"
        for _ in range(30):
            obs, _, dones, _, infos = env.step(np.array([1, 1], dtype=np.int64))
            if dones.any():
                assert np.array_equal(infos["_final_obs"], dones)
                for i in np.where(dones)[0]:
                    assert infos["final_info"][i]["state"]["done"]
                    assert not env._remote.states[i]["done"]
                    assert not np.array_equal(obs[i], infos["final_obs"][i])
                break
        else:
            pytest.fail("straight-moving snakes should hit wall")
    finally:
        env.close()


@pytest.fixture
def fake_openenv(monkeypatch):
    """Official StepResult shape, injectable failures, no actual network."""
    class Client:
        instances = []
        failure = None  # (operation, slot index, invocation count)
        terminal_slots = set()
        environment = {"game": "snake", "name": "Snake", "actions": [0, 1, 2],
                       "obs_modes": ["grid"], "schemas": {}, "meta": {},
                       "version": "1.2.3", "max_concurrent_envs": 64}

        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.index = len(self.instances)
            self.instances.append(self)
            self.calls = {key: [] for key in ("connect", "state", "reset", "step", "close")}
            self.step_count = 0

        def sync(self):
            return self

        def record(self, operation, payload=None):
            self.calls[operation].append(deepcopy(payload))
            if self.failure == (operation, self.index, len(self.calls[operation])):
                raise RuntimeError("injected failure")

        def connect(self):
            self.record("connect")

        def state(self):
            self.record("state")
            return {"episode_id": None, "step_count": 0, "game_state": None,
                    "environment": deepcopy(self.environment)}

        def reset(self, **kwargs):
            self.record("reset", kwargs)
            self.config = deepcopy(kwargs)
            self.step_count = 0
            return self.result(reset=True)

        def step(self, action):
            self.record("step", action)
            self.step_count += 1
            return self.result()

        def result(self, reset=False):
            done = not reset and self.index in self.terminal_slots
            state = {"seed": self.config["seed"], "body": [[3, 2], [2, 2]],
                     "food": [6, 6], "grid": [10, 10], "direction": 3,
                     "done": done, "score": self.step_count, "lines": 0}
            metadata = {}
            if reset:
                metadata["environment"] = {**deepcopy(self.environment),
                                           "version": self.config["version"]}
            mode = self.config["obs_mode"]
            observation = {"type": "state" if mode == "state" else "tensor",
                           "data": [] if mode == "state" else [0, self.step_count],
                           "shape": [] if mode == "state" else [1, 2],
                           "dtype": "float32", "state": state, "metadata": metadata}
            return StepResult(observation=observation, reward=0 if reset else 2.5, done=done)

        def close(self):
            self.record("close")

    def no_http(*args, **kwargs):
        pytest.fail("environment SDK must not use requests")

    monkeypatch.setattr("gameplatform.remote.GenericEnvClient", Client)
    monkeypatch.setattr(requests.Session, "request", no_http)
    return Client


@pytest.mark.parametrize("mode,dim", [("features", 11), ("rotwin", 254),
                                     ("reach", 9), ("state", None), ("grid", 2)])
def test_remote_official_reset_modes_and_actions(fake_openenv, mode, dim):
    with RemoteVecEnv(n=2, obs_mode=mode, seed=0, timeout=3,
                      rewards={"step": np.float32(-.5)},
                      new_options={"size": np.array([10, 10])}) as env:
        assert env.game_version == "1.2.3"
        assert env.max_concurrent_envs == 64
        if dim is not None:
            assert env.obs_dim == dim
        else:
            assert env._last_obs == env.states
        for i, client in enumerate(fake_openenv.instances):
            assert client.kwargs == {"base_url": "http://127.0.0.1:8080/api/openenv/snake",
                                     "connect_timeout_s": 3, "message_timeout_s": 3,
                                     "mode": "simulation"}
            assert client.calls["reset"] == [{"seed": i, "version": "1.2.3",
                "include_state": True, "obs_mode": "grid" if mode == "grid" else "state",
                "rewards": {"step": -.5}, "options": {"size": [10, 10]}}]
        _, rewards, dones, _ = env.step(np.array([1, 2], dtype=np.int64))
        np.testing.assert_array_equal(rewards, [2.5, 2.5])
        assert not dones.any()
        assert [c.calls["step"] for c in fake_openenv.instances] == [[{"value": 1}], [{"value": 2}]]
        # Composite raw actions receive exactly one value envelope, too.
        env.step([[{"unit": np.int64(7), "move": np.array([1, 2])}], []])
        assert fake_openenv.instances[0].calls["step"][-1] == {
            "value": [{"unit": 7, "move": [1, 2]}]}
    assert all(len(c.calls["close"]) == 1 for c in fake_openenv.instances)


def test_remote_server_mode_takes_precedence_over_local_function(fake_openenv):
    fake_openenv.environment["obs_modes"].append("rotwin")
    with RemoteVecEnv(n=1, obs_mode="rotwin", R=1) as env:
        assert env.obs_dim == 2  # fake server shape, not the local R=1 feature shape
        assert fake_openenv.instances[0].calls["reset"][0]["obs_mode"] == "rotwin"


def test_remote_pins_version_seeds_and_autoreset(fake_openenv):
    fake_openenv.terminal_slots = {0}
    with RemoteVecEnv(n=2, seed=0, obs_mode="grid") as env:
        fake_openenv.environment["version"] = "9.9.9"  # a later deployment
        obs, _, dones, infos = env.step([1, 1])
        np.testing.assert_array_equal(dones, [True, False])
        assert infos[0]["state"]["seed"] == 0 and infos[0]["state"]["done"]
        np.testing.assert_array_equal(env.terminal_obs(infos[0]), [[0, 1]])
        np.testing.assert_array_equal(obs[0], [[0, 0]])
        assert [s["seed"] for s in env.states] == [100003, 1]
        assert [len(c.calls["reset"]) for c in fake_openenv.instances] == [2, 1]
        env.reset(seed=[7, 11], options={"size": 8})
        assert [s["seed"] for s in env.states] == [7, 11]
        env.reset()
        assert [s["seed"] for s in env.states] == [100010, 100014]
        assert all(r["version"] == "1.2.3" for c in fake_openenv.instances for r in c.calls["reset"])
        assert env.info["version"] == "1.2.3"


@pytest.mark.parametrize("operation,index,count", [("connect", 1, 1), ("state", 0, 1),
    ("reset", 1, 1), ("step", 1, 1), ("reset", 0, 2)])
def test_remote_failure_closes_partial_vector_without_retry(fake_openenv, operation, index, count):
    fake_openenv.failure = (operation, index, count)
    fake_openenv.terminal_slots = {0}
    env = None
    with pytest.raises(RuntimeError, match="injected failure"):
        env = RemoteVecEnv(n=3, obs_mode="grid")
        env.step([1, 1, 1])
    assert all(len(c.calls["close"]) == 1 for c in fake_openenv.instances)
    assert len(fake_openenv.instances[index].calls[operation]) == count
    if env is not None:
        with pytest.raises(RuntimeError, match="closed"):
            env.step([1, 1, 1])
        with pytest.raises(RuntimeError, match="closed"):
            env.reset()
        env.close()  # idempotent, including official sync-loop cleanup
        assert all(len(c.calls["close"]) == 1 for c in fake_openenv.instances)


@pytest.mark.parametrize("limit,n", [(64, 65), (64, 10**9), (2, 3)])
def test_remote_enforces_advertised_connection_limit(fake_openenv, limit, n):
    fake_openenv.environment["max_concurrent_envs"] = limit
    with pytest.raises(ValueError, match=f"max_concurrent_envs={limit}"):
        RemoteVecEnv(n=n)
    assert len(fake_openenv.instances) == 1
    assert fake_openenv.instances[0].calls["reset"] == []
    assert len(fake_openenv.instances[0].calls["close"]) == 1


def test_remote_close_continues_after_broken_slot(fake_openenv):
    env = RemoteVecEnv(n=3)
    fake_openenv.failure = ("close", 0, 1)
    env.close()
    env.close()
    assert all(len(c.calls["close"]) == 1 for c in fake_openenv.instances)


@pytest.mark.parametrize("wrapper", [PlatformRemoteEnv, PlatformRemoteVecEnv])
def test_gym_space_failure_closes_sessions(fake_openenv, monkeypatch, wrapper):
    def fail_space(*args):
        raise ValueError("invalid space")
    monkeypatch.setattr("gameplatform.gym._obs_space", fail_space)
    with pytest.raises(ValueError, match="invalid space"):
        wrapper(obs_mode="grid")
    assert all(len(c.calls["close"]) == 1 for c in fake_openenv.instances)


@pytest.mark.parametrize("mode,shape", [("features", (2, 11)), ("rotwin", (2, 1334)),
                                       ("reach", (2, 9)), ("state", None)])
def test_live_raw_state_modes_and_socket_cleanup(base_url, mode, shape):
    with RemoteVecEnv(n=2, obs_mode=mode, base_url=base_url, seed=42) as env:
        clients = list(env._clients)
        assert all(isinstance(c.async_client, GenericEnvClient) for c in clients)
        assert env.info["max_concurrent_envs"] == 64
        if shape:
            assert env._last_obs.shape == shape
        assert [s["seed"] for s in env.states] == [42, 43]
        env.step(np.array([1, 1]))
        for i, client in enumerate(clients):
            state = client.state()
            assert state["step_count"] == 1
            assert state["game_state"] == env.states[i]
            assert state["environment"]["version"] == env.game_version
    assert all(c.async_client._ws is None and c._loop_thread is None for c in clients)


@pytest.mark.parametrize("game", ["snake", "tetris"])
def test_training_and_evaluation_close_sessions(fake_openenv, monkeypatch, game):
    import importlib.util
    import torch
    spec = importlib.util.spec_from_file_location(f"cleanup_{game}", ROOT / "training" / f"{game}_dqn.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "DEVICE", "cpu")
    monkeypatch.setattr(sys, "argv", [spec.origin, "--envs", "2"])

    def fail_train(*args):
        raise RuntimeError("training interrupted")
    monkeypatch.setattr(module, "train", fail_train)
    with pytest.raises(RuntimeError, match="training interrupted"):
        module.main()
    assert all(len(c.calls["close"]) == 1 for c in fake_openenv.instances)

    fake_openenv.terminal_slots = set(range(10))
    args = SimpleNamespace(base_url="http://127.0.0.1:8080", obs="grid")
    module.evaluate(torch.nn.Linear(2, 4), args, episodes=3)
    assert len(fake_openenv.instances) == 5  # two training + three single-episode evals
    assert all(len(c.calls["close"]) == 1 for c in fake_openenv.instances)
    assert all(len(c.calls["reset"]) == 1 for c in fake_openenv.instances)

    def fail_policy(_):
        raise RuntimeError("evaluation interrupted")
    with pytest.raises(RuntimeError, match="evaluation interrupted"):
        module.evaluate(fail_policy, args, episodes=1)
    assert all(len(c.calls["close"]) == 1 for c in fake_openenv.instances)

