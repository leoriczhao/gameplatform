"""Remote vectorized RL environment client for Stream.

Each slot owns an official OpenEnv WebSocket session at /api/openenv/{game}/ws.
This module wraps GenericEnvClient into a vectorized, gym-style interface:

    from gameplatform import RemoteVecEnv
    with RemoteVecEnv(game="snake", n=16, obs_mode="features") as envs:
        obs = envs.reset(seed=42)
        while training:
            actions = agent.act(obs)             # your model, local torch
            obs, rewards, dones, infos = envs.step(actions)

Model/training compute runs on YOUR machine. Slots advance synchronously in
order: n WebSocket round trips per step, not one batch HTTP request. Throughput
is therefore latency-sensitive. n cannot exceed the game's max_concurrent_envs
(currently 64, shared with other connections). Failed steps are NEVER retried;
any transport/protocol failure closes the whole vector, whose partial progress
is unknown. Create a new vector explicitly to start fresh episodes.

obs_mode:
  server-side (per game, see OpenEnv state()["environment"]["obs_modes"]):
    "grid"    snake: 3x22x22 padded grid · tetris: 2x20x10 board channels
    "rotwin"  bundled snake: 1334 dims (fixed server-side R=10)
  client-side (snake only, unless the server declares the same mode):
    "features" 11-dim heading-relative features
    "rotwin"   (2R+1)^2*3 + 11 dims rotation-normalized window
    "reach"    9-dim clearance/room features
  "state"    raw state dicts (advanced; no fixed dim)
"""
from __future__ import annotations

from urllib.parse import quote

import numpy as np
from openenv.core import GenericEnvClient

from .games import make_obs_fn

DEFAULT_BASE_URL = "http://127.0.0.1:8080"


def _json_value(value):
    """Normalize NumPy scalars/arrays, including composite nested actions."""
    if isinstance(value, np.ndarray):
        return _json_value(value.tolist())
    if isinstance(value, np.generic):
        return _json_value(value.item())
    if isinstance(value, (list, tuple)):
        return [_json_value(v) for v in value]
    if isinstance(value, dict):
        return {k: _json_value(v) for k, v in value.items()}
    return value


class RemoteVecEnv:
    """n persistent OpenEnv sessions, advanced sequentially without step retries."""

    def __init__(self, game: str = "snake", n: int = 16,
                 base_url: str = DEFAULT_BASE_URL, seed: int = 0,
                 obs_mode: str = "state", R: int = 4,
                 rewards: dict | None = None, timeout: float = 15.0,
                 new_options: dict | None = None, autoreset: bool = True):
        if isinstance(n, bool) or not isinstance(n, (int, np.integer)) or n < 1:
            raise ValueError("n must be a positive integer")
        self.autoreset = autoreset
        self.game = game
        self.n = int(n)
        self.base_url = base_url.rstrip("/")
        self.obs_mode = obs_mode
        self.R = R
        self.rewards = rewards  # sent only on reset; fixed for that episode
        self.timeout = timeout
        self.new_options = new_options  # OpenEnv reset options (e.g. microrts opponent)
        self._clients = []
        self._closed = False
        self.states: list[dict] | None = None
        self._last_obs: np.ndarray | list | None = None

        try:
            # state() is available before reset and describes the current version.
            self.info = self._connect_slot().state()["environment"]
            self.game_version = self.info["version"]
            self.server_modes = list(self.info.get("obs_modes") or [])
            self.actions = list(self.info["actions"])
            self.num_actions = len(self.actions)
            self.max_concurrent_envs = int(self.info["max_concurrent_envs"])
            if n > self.max_concurrent_envs:
                raise ValueError(f"n={n} exceeds {game} "
                                 f"max_concurrent_envs={self.max_concurrent_envs}")
            self._episode_seeds = [int(seed) + i for i in range(n)]
            self._dones = np.zeros(n, dtype=bool)

            self._obs_fn = make_obs_fn(game, obs_mode, R)
            if obs_mode != "state" and not self._wants_server_obs() \
                    and self._obs_fn is None:
                raise ValueError(
                    f"unknown obs_mode {obs_mode!r} for game {game!r} "
                    f"(server: {self.server_modes}, client: features/rotwin/reach/state)")

            for _ in range(1, n):
                self._connect_slot()
            self.reset()
        except BaseException:
            self.close()  # includes partial connection setup and KeyboardInterrupt
            raise

    # --------------------------------------------------------------- OpenEnv
    def _connect_slot(self):
        client = GenericEnvClient(
            base_url=f"{self.base_url}/api/openenv/{quote(self.game, safe='')}",
            connect_timeout_s=self.timeout, message_timeout_s=self.timeout,
            mode="simulation").sync()
        self._clients.append(client)  # own it BEFORE connect can fail
        client.connect()
        return client

    def _ensure_open(self):
        if self._closed:
            raise RuntimeError("RemoteVecEnv is closed; create a new environment")

    def _wants_server_obs(self) -> bool:
        return self.obs_mode != "state" and self.obs_mode in self.server_modes

    def _reset_one(self, i):
        payload = {"seed": self._episode_seeds[i], "version": self.game_version,
                   "obs_mode": self.obs_mode if self._wants_server_obs() else "state",
                   "include_state": True}
        if self.new_options is not None:
            payload["options"] = self.new_options
        if self.rewards is not None:
            payload["rewards"] = self.rewards
        result = self._clients[i].reset(**_json_value(payload))
        environment = result.observation["metadata"]["environment"]
        if environment["version"] != self.game_version:
            raise RuntimeError("OpenEnv reset changed the pinned game version")
        self._episode_seeds[i] += 100003
        return result

    def _unpack(self, result):
        observation = result.observation  # official StepResult, not an HTTP envelope
        state = observation["state"]
        if not isinstance(state, dict):
            raise RuntimeError("OpenEnv response omitted full state despite include_state=True")
        server_obs = None
        if self._wants_server_obs():
            if observation["type"] != "tensor":
                raise RuntimeError("expected an OpenEnv tensor observation")
            server_obs = np.asarray(observation["data"], dtype=np.float32).reshape(
                observation["shape"])
        return state, server_obs

    # ------------------------------------------------------------ gym-ish api
    def reset(self, *, seed=None, options=None) -> np.ndarray | list:
        """Reset every slot; seeds advance by 100003 per episode in each slot.

        A scalar seed assigns seed+i to slot i; a list specifies each slot's seed.
        Calling reset(seed=...) again reproduces that initial observation.
        """
        self._ensure_open()
        if seed is not None:
            seeds = ([int(seed) + i for i in range(self.n)] if np.isscalar(seed)
                     else [int(s) for s in seed])
            if len(seeds) != self.n:
                raise ValueError("one seed required per environment")
            self._episode_seeds = seeds
        if options is not None:
            self.new_options = options
        try:
            results = [self._reset_one(i) for i in range(self.n)]
            unpacked = [self._unpack(r) for r in results]
            self.states = [s for s, _ in unpacked]
            self._last_obs = self._obs(self.states, [o for _, o in unpacked])
            self._dones = np.asarray([r.done for r in results], dtype=bool)
            self.info = results[0].observation["metadata"]["environment"]
            return self._last_obs
        except BaseException:
            self.close()
            raise

    def step(self, actions) -> tuple[np.ndarray | list, np.ndarray, np.ndarray, list[dict]]:
        self._ensure_open()
        if len(actions) != self.n:
            raise ValueError("one action required per environment")
        if self._dones.any():
            raise RuntimeError("episode has ended; call reset() before step()")
        try:
            # No state, reset configuration, reconnect, or retry on this path.
            # A failed later slot may leave earlier slots advanced: close them all.
            results = [client.step({"value": _json_value(action)})
                       for client, action in zip(self._clients, actions)]
            unpacked = [self._unpack(r) for r in results]
            rewards = np.asarray([r.reward for r in results], dtype=np.float32)
            dones = np.asarray([r.done for r in results], dtype=bool)
            infos = []
            for s, server_obs in unpacked:
                info = {"state": s, "cause": s.get("cause"), "score": s.get("score")}
                for key in ("ate", "lines"):
                    if key in s:
                        info[key] = s[key]
                if self._wants_server_obs():
                    info["terminal_obs"] = server_obs  # pre-reset observation
                infos.append(info)

            next_states = [s for s, _ in unpacked]
            server_objs = [o for _, o in unpacked]
            self._dones = dones.copy()
            if self.autoreset:
                for i in np.flatnonzero(dones):
                    fresh = self._reset_one(i)
                    next_states[i], server_objs[i] = self._unpack(fresh)
                    self._dones[i] = fresh.done
            self.states = next_states
            self._last_obs = self._obs(next_states, server_objs)
            return self._last_obs, rewards, dones, infos
        except BaseException:
            self.close()
            raise

    def terminal_obs(self, info: dict):
        """Observation of the terminal (pre-reset) state for one env."""
        if self.obs_mode == "state":
            return info["state"]
        if self._wants_server_obs():
            return np.asarray(info["terminal_obs"], dtype=np.float32)
        return self._obs_fn(info["state"]).astype(np.float32)

    # -------------------------------------------------------------------- obs
    def _obs(self, states, server_objs) -> np.ndarray | list:
        if self.obs_mode == "state":
            return states
        if self._wants_server_obs():
            return np.asarray(server_objs, dtype=np.float32)
        batch = [self._obs_fn(s) for s in states]
        return np.stack(batch).astype(np.float32)

    @property
    def obs_dim(self) -> int:
        if self.obs_mode == "state":
            raise ValueError("state mode has no fixed obs dim")
        return int(np.prod(np.asarray(self._last_obs[0]).shape))

    def close(self):
        """Release every socket and official sync-client loop; safe to repeat."""
        self._closed = True
        clients, self._clients = self._clients, []
        for client in clients:
            try:
                client.close()
            except Exception:
                pass  # a broken slot must not prevent closing the others

    def __enter__(self):
        self._ensure_open()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
