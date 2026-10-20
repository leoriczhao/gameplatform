"""Gymnasium-compatible wrappers for the platform — the "universal" game-RL
interface that stable-baselines3, CleanRL, RLlib, SBX etc. all consume.

Importing this module registers one env per bundled game, so any standard
framework can use them out of the box:

    import gameplatform.gym as gpgym       # registers 'platform-snake-v0'
    import gymnasium as gym

    with gym.make("platform-snake-v0", obs_mode="rotwin") as env:
        obs, info = env.reset()
        obs, reward, terminated, truncated, info = env.step(action)  # 5-tuple

        from stable_baselines3 import PPO
        model = PPO("MlpPolicy", env).learn(total_timesteps=100_000)

Two wrappers:
  PlatformRemoteEnv     single env (gymnasium.Env)
  PlatformRemoteVecEnv  n persistent WS slots (gymnasium.VectorEnv, n <= 64)

Both use RemoteVecEnv with official OpenEnv clients: slots advance sequentially,
not in a batch HTTP request. The training algorithm runs on your machine;
transitions run on the server. Always close the wrapper (or use a with block).
A transport/protocol failure closes all slots and is never retried.

Only discrete-action games (snake, tetris) are registered here. Composite
action games (e.g. microrts) expose a per-unit command list, so use
RemoteVecEnv directly and encode/decode commands yourself (or export an
ONNX model through the platform model contract).
"""
from __future__ import annotations

import gymnasium as gym
import numpy as np
from gymnasium import spaces
from gymnasium.vector.utils import batch_space
from gymnasium.vector.vector_env import AutoresetMode

from .remote import RemoteVecEnv

REGISTERED_GAMES = ("snake", "tetris")


def _obs_space(obs_mode: str, obs: np.ndarray) -> spaces.Box:
    a = np.asarray(obs)
    return spaces.Box(low=0.0, high=1.0, shape=tuple(a.shape[1:]), dtype=np.float32)


class PlatformRemoteEnv(gym.Env):
    """One OpenEnv WebSocket; terminated episodes require an explicit reset."""

    metadata = {"render_modes": []}

    def __init__(self, game: str = "snake", obs_mode: str = "features",
                 base_url: str = "http://127.0.0.1:8080", seed: int = 0,
                 R: int = 4, rewards: dict | None = None, timeout: float = 15.0):
        super().__init__()
        assert obs_mode != "state", "gym wrappers need a numeric obs mode"
        self._cfg = dict(game=game, obs_mode=obs_mode, base_url=base_url, R=R,
                         rewards=rewards, timeout=timeout)
        self._remote = RemoteVecEnv(n=1, seed=seed, autoreset=False, **self._cfg)
        try:
            obs = self._remote._last_obs
            self.observation_space = _obs_space(obs_mode, obs)
            self.action_space = spaces.Discrete(self._remote.num_actions)
        except BaseException:
            self._remote.close()
            raise

    def reset(self, *, seed: int | None = None, options: dict | None = None):
        super().reset(seed=seed)
        obs = self._remote.reset(seed=seed, options=options)
        state = self._remote.states[0]
        return obs[0], {"state": state, "seed": state.get("seed")}

    def step(self, action):
        obs, reward, dones, infos = self._remote.step([int(action)])
        info = dict(infos[0])
        return obs[0], float(reward[0]), bool(dones[0]), False, info


    def close(self):
        self._remote.close()


class PlatformRemoteVecEnv(gym.vector.VectorEnv):
    """n OpenEnv WS sessions, advanced sequentially (latency-sensitive).

    SAME_STEP autoreset: terminated slots return the new episode observation,
    with terminal observations in infos["final_obs"] and matching masks.
    """

    def __init__(self, game: str = "snake", n: int = 16,
                 obs_mode: str = "features",
                 base_url: str = "http://127.0.0.1:8080", seed: int = 0,
                 R: int = 4, rewards: dict | None = None, timeout: float = 15.0):
        assert obs_mode != "state", "gym wrappers need a numeric obs mode"
        self._cfg = dict(game=game, n=n, obs_mode=obs_mode, base_url=base_url,
                         seed=seed, R=R, rewards=rewards, timeout=timeout)
        self._remote = RemoteVecEnv(**self._cfg)
        try:
            self._obs = self._remote._last_obs

            self.num_envs = n
            self.render_mode = None
            self.single_action_space = spaces.Discrete(self._remote.num_actions)
            self.single_observation_space = _obs_space(obs_mode, self._obs)
            self.action_space = batch_space(self.single_action_space, n)
            self.observation_space = batch_space(self.single_observation_space, n)
            self.metadata = {"autoreset_mode": AutoresetMode.SAME_STEP,
                             "render_modes": []}
        except BaseException:
            self._remote.close()
            raise

    # gymnasium 1.x: VectorEnv.reset/step are abstract; implement directly.
    def reset(self, *, seed=None, options=None):
        self._obs = self._remote.reset(seed=seed, options=options)
        return self._obs, {}

    def step(self, actions):
        obs, rew, dones, infos = self._remote.step(actions)
        self._obs = obs
        packed = self._pack_infos(infos)
        if np.any(dones):
            final_obs = np.full(self.num_envs, None, dtype=object)
            final_info = np.full(self.num_envs, None, dtype=object)
            for i in np.where(dones)[0]:
                final_obs[i] = self._remote.terminal_obs(infos[i])
                final_info[i] = infos[i]
            packed.update(final_obs=final_obs, _final_obs=dones.copy(),
                          final_info=final_info, _final_info=dones.copy())
        return obs, rew, dones, np.zeros(self.num_envs, dtype=bool), packed

    @staticmethod
    def _pack_infos(infos: list[dict]) -> dict:
        # list-of-dicts -> dict-of-arrays (+ _key masks), like the base class
        packed: dict = {}
        for i, info in enumerate(infos):
            for key, value in info.items():
                if key == "state" or key in ("terminal_obs",):
                    value = None  # not packable; kept out of the arrays
                if key not in packed:
                    if isinstance(value, (int, float, bool, np.integer, np.floating)):
                        packed[key] = np.zeros(len(infos), dtype=type(value) if not
                                              isinstance(value, np.generic) else value.dtype)
                    elif isinstance(value, np.ndarray):
                        packed[key] = np.zeros((len(infos), *value.shape), dtype=value.dtype)
                    else:
                        packed[key] = np.full(len(infos), None, dtype=object)
                    packed[f"_{key}"] = np.zeros(len(infos), dtype=bool)
                if value is None:
                    continue
                packed[key][i] = value
                packed[f"_{key}"][i] = True
        return packed

    def get_attr(self, name):
        return [getattr(self._remote, name)] * self.num_envs

    def set_attr(self, name, values):
        setattr(self._remote, name, values[0])

    def close(self, **kwargs):
        self._remote.close()
        self.closed = True


def _register():
    for game in REGISTERED_GAMES:
        try:
            gym.register(id=f"platform-{game}-v0",
                         entry_point="gameplatform.gym:PlatformRemoteEnv",
                         kwargs={"game": game})
        except gym.error.Error:
            pass  # already registered


_register()
