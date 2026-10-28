"""Local training: run the platform's own game package in-process.

The platform distributes every official game package (and UGC packages whose
author opted in with ``local_training: true``). The SDK downloads the exact
version, verifies its sha256, caches it, and imports it into your Python
process, so ``step`` costs microseconds instead of a WebSocket round trip:

    from gameplatform import LocalVecEnv
    with LocalVecEnv(game="snake", n=64, obs_mode="rotwin",
                     base_url="https://games.cree1p.com") as envs:
        obs = envs.reset(seed=42)
        obs, rewards, dones, infos = envs.step(actions)

LocalVecEnv has the same constructor arguments, seeds, observations, rewards
and infos as RemoteVecEnv. The package code and the episode rules are the ones
the server runs (one engine, D3), and every value crosses the same JSON
boundary the server's sandbox uses, so ``parity_check`` can prove a local
trajectory equals the remote one step for step.

UGC packages are third-party code. Pass ``trust_remote_code=True`` to run one;
official packages run without it.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import quote

import numpy as np
import requests
from gamekernel import models as kernel_models
from gamekernel.calls import GameCalls
from gamekernel.episode import Episode, checked_rewards
from gamekernel.loader import load_package

from .games import make_obs_fn
from .remote import DEFAULT_BASE_URL, _json_value

contract_of = kernel_models.contract_of  # the package's model contract (normalized)

def cache_root() -> Path:
    """$GAMEPLATFORM_CACHE, else ~/.cache/gameplatform (read on every call)."""
    return Path(os.environ.get("GAMEPLATFORM_CACHE")
                or Path.home() / ".cache" / "gameplatform")

EPISODE_SEED_STRIDE = 100003  # same per-episode seed advance as RemoteVecEnv


# ------------------------------------------------------------------ packages

def _safe_extract(data: bytes, dest: Path) -> None:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for name in zf.namelist():
            parts = Path(name).parts
            if name.startswith(("/", "\\")) or ".." in parts or ":" in name.split("/")[0]:
                raise ValueError(f"unsafe path in package: {name}")
        zf.extractall(dest)


def fetch_package(game: str, version: str | None = None, *,
                  base_url: str = DEFAULT_BASE_URL, cache_dir: str | Path | None = None,
                  trust_remote_code: bool = False, timeout: float = 30.0) -> Path:
    """Download (or reuse from cache) one game package; return its directory.

    With an explicit ``version`` already in the cache, no network is used.
    Each cache entry is keyed by slug, version and sha256 and written
    atomically, so an interrupted download never leaves a half package.
    """
    root = Path(cache_dir or cache_root()) / "games" / game
    if version is not None:
        for entry in sorted(root.glob(f"{version}-*")):
            manifest = _read_manifest(entry)
            if manifest and manifest["version"] == version:
                _check_trust(manifest, trust_remote_code)
                return entry
    base = base_url.rstrip("/")
    resp = requests.get(f"{base}/api/v1/games/{quote(game, safe='')}/package",
                        params={"version": version} if version else None, timeout=timeout)
    if resp.status_code != 200:
        raise RuntimeError(f"package manifest for {game!r} unavailable "
                           f"({resp.status_code}): {_detail(resp)}")
    manifest = resp.json()
    _check_trust(manifest, trust_remote_code)
    dest = root / f"{manifest['version']}-{manifest['sha256'][:12]}"
    if _read_manifest(dest):
        return dest
    blob = requests.get(base + manifest["url"], timeout=timeout)
    if blob.status_code != 200:
        raise RuntimeError(f"package download failed ({blob.status_code}): {_detail(blob)}")
    data = blob.content
    if len(data) != manifest["size"] or hashlib.sha256(data).hexdigest() != manifest["sha256"]:
        raise RuntimeError(f"package {game} {manifest['version']} failed its sha256 check")
    root.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=".partial-", dir=root))
    try:
        _safe_extract(data, tmp)
        (tmp / ".manifest.json").write_text(json.dumps(manifest, ensure_ascii=False),
                                            encoding="utf-8")
        try:
            tmp.rename(dest)
        except OSError:
            if not _read_manifest(dest):  # lost a race to another process: fine
                raise
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return dest


def _read_manifest(entry: Path) -> dict | None:
    try:
        return json.loads((entry / ".manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _check_trust(manifest: dict, trust_remote_code: bool) -> None:
    if not manifest.get("official") and not trust_remote_code:
        raise PermissionError(
            f"{manifest['slug']} {manifest['version']} is a community (UGC) package; "
            "it runs as Python code on your machine. Pass trust_remote_code=True to run it.")


def _detail(resp) -> str:
    try:
        return str(resp.json().get("detail"))
    except ValueError:
        return resp.text[:200]


class LocalGame:
    """One game package imported in-process behind the kernel's call semantics
    (gamekernel.calls), with the sandbox's JSON boundary on every output."""

    def __init__(self, path: str | Path, meta: dict | None = None):
        self.path = Path(path).resolve()
        manifest = _read_manifest(self.path)
        if meta is None:
            meta = manifest["meta"] if manifest else _load_yaml(self.path / "game.yaml")
        self.meta = meta
        self.slug = meta["slug"]
        self.version = str(meta.get("version"))
        self.official = bool(manifest and manifest.get("official"))
        digest = hashlib.sha256(str(self.path).encode()).hexdigest()[:10]
        self.calls = GameCalls(
            load_package(self.path, f"_gameplatform_pkg_{self.slug.replace('-', '_')}_{digest}"),
            wire_outputs=True)
        info = self.calls.info()
        info = info if isinstance(info, dict) else {}
        board = meta.get("board") or {}
        if board.get("width") and board.get("height"):
            info.setdefault("grid", [board["width"], board["height"]])  # as ProxyAdapter
        self.info = info

    @property
    def contract(self) -> dict | None:
        return contract_of(self.meta)

    @property
    def obs_modes(self) -> list[str]:
        return list(self.info.get("obs_modes") or [])

    @property
    def opponents(self) -> list[str]:
        return list(self.meta.get("opponents") or [])

    # NumPy inputs are normalized the way RemoteVecEnv serializes them.
    def new_state(self, seed: int, options: dict | None = None) -> dict:
        return self.calls.new_state(int(seed), _json_value(options))

    def step_state(self, state: dict, action, rewards: dict | None = None) -> dict:
        return self.calls.step_state(state, _json_value(action), rewards)

    def validate_state(self, state: dict) -> None:
        self.calls.validate_state(state)

    def validate_action(self, action, state: dict | None = None) -> None:
        self.calls.validate_action(_json_value(action), state)

    def obs(self, state: dict, mode: str | None = None):
        return self.calls.obs(state, mode)

    def obs_array(self, state: dict, mode: str | None = None) -> np.ndarray | None:
        return self.calls.obs_array(state, mode)

    def opponent_action(self, state: dict, config: dict):
        return self.calls.opponent_action(state, config)

    def sample_action(self, state: dict):
        return self.calls.sample_action(state)

    def model_inputs(self, state: dict, owner: int = 0):
        return self.calls.model_inputs(state, owner)

    def model_decode(self, outputs, state: dict, owner: int = 0):
        return self.calls.model_decode(outputs, state, owner)


def _load_yaml(path: Path) -> dict:
    try:
        import yaml
    except ImportError as e:  # pragma: no cover
        raise ImportError("loading a package directory without a platform manifest "
                          "needs PyYAML: pip install pyyaml") from e
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_game(game: str | Path, version: str | None = None, *,
              base_url: str = DEFAULT_BASE_URL, cache_dir: str | Path | None = None,
              trust_remote_code: bool = False) -> LocalGame:
    """A slug downloads from the platform; an existing directory (e.g. your own
    package under development) is loaded as is."""
    if isinstance(game, Path) or os.sep in game or game.startswith("."):
        return LocalGame(game)
    return LocalGame(fetch_package(game, version, base_url=base_url, cache_dir=cache_dir,
                                   trust_remote_code=trust_remote_code))


# ------------------------------------------------------------------ vector env

class LocalVecEnv:
    """n in-process episodes with RemoteVecEnv's exact interface and semantics."""

    def __init__(self, game: str | Path = "snake", n: int = 16,
                 base_url: str = DEFAULT_BASE_URL, seed: int = 0,
                 obs_mode: str = "state", R: int = 4,
                 rewards: dict | None = None, timeout: float = 30.0,
                 new_options: dict | None = None, autoreset: bool = True, *,
                 version: str | None = None, cache_dir: str | Path | None = None,
                 trust_remote_code: bool = False):
        if isinstance(n, bool) or not isinstance(n, (int, np.integer)) or n < 1:
            raise ValueError("n must be a positive integer")
        self.runtime = game if isinstance(game, LocalGame) else load_game(
            game, version, base_url=base_url, cache_dir=cache_dir,
            trust_remote_code=trust_remote_code)
        self.game = self.runtime.slug
        self.game_version = self.runtime.version
        self.n = int(n)
        self.obs_mode = obs_mode
        self.R = R
        self.autoreset = autoreset
        self.new_options = new_options
        self.info = dict(self.runtime.info, game=self.game, version=self.game_version)
        self.server_modes = self.runtime.obs_modes
        self.actions = list(self.info.get("actions") or [])
        self.num_actions = len(self.actions)
        self.rewards = checked_rewards(self.info, rewards)
        self._episodes = [Episode(self.runtime, self.info, rewards) for _ in range(self.n)]
        self._closed = False
        self.states: list[dict] | None = None
        self._last_obs = None
        self._episode_seeds = [int(seed) + i for i in range(self.n)]
        self.current_seeds: list[int | None] = [None] * self.n  # seed of each slot's episode
        self._dones = np.zeros(self.n, dtype=bool)
        self._obs_fn = make_obs_fn(self.game, obs_mode, R)
        if obs_mode != "state" and not self._wants_server_obs() and self._obs_fn is None:
            raise ValueError(
                f"unknown obs_mode {obs_mode!r} for game {self.game!r} "
                f"(package: {self.server_modes}, client: features/rotwin/reach/state)")
        self.reset()

    def _ensure_open(self):
        if self._closed:
            raise RuntimeError("LocalVecEnv is closed; create a new environment")

    def _wants_server_obs(self) -> bool:
        return self.obs_mode != "state" and self.obs_mode in self.server_modes

    def _reset_one(self, i: int) -> dict:
        state = self._episodes[i].reset(self._episode_seeds[i], self.new_options)
        self.current_seeds[i] = self._episode_seeds[i]
        self._episode_seeds[i] += EPISODE_SEED_STRIDE
        return state

    def _server_obs(self, state: dict) -> np.ndarray:
        obs = self.runtime.obs_array(state, self.obs_mode)
        if obs is None:
            raise ValueError(f"observation mode {self.obs_mode!r} returned no data")
        return obs

    def reset(self, *, seed=None, options=None):
        self._ensure_open()
        if seed is not None:
            seeds = ([int(seed) + i for i in range(self.n)] if np.isscalar(seed)
                     else [int(s) for s in seed])
            if len(seeds) != self.n:
                raise ValueError("one seed required per environment")
            self._episode_seeds = seeds
        if options is not None:
            self.new_options = options
        self.states = [self._reset_one(i) for i in range(self.n)]
        self._dones = np.asarray([bool(s.get("done", False)) for s in self.states])
        self._last_obs = self._obs(self.states)
        return self._last_obs

    def step(self, actions):
        self._ensure_open()
        if len(actions) != self.n:
            raise ValueError("one action required per environment")
        if self._dones.any():
            raise RuntimeError("episode has ended; call reset() before step()")
        next_states, rewards, dones, infos, server_obs = [], [], [], [], []
        for ep, action in zip(self._episodes, actions):
            nxt, reward, done = ep.step(_json_value(action))
            next_states.append(nxt)
            rewards.append(float("nan") if reward is None else reward)  # as RemoteVecEnv
            dones.append(done)
            info = {"state": nxt, "cause": nxt.get("cause"), "score": nxt.get("score")}
            for key in ("ate", "lines"):
                if key in nxt:
                    info[key] = nxt[key]
            if self._wants_server_obs():
                server_obs.append(self._server_obs(nxt))
                info["terminal_obs"] = server_obs[-1]  # pre-reset observation
            infos.append(info)
        dones = np.asarray(dones, dtype=bool)
        self._dones = dones.copy()
        if self.autoreset:
            for i in np.flatnonzero(dones):
                next_states[i] = self._reset_one(i)
                self._dones[i] = bool(next_states[i].get("done", False))
                if server_obs:
                    server_obs[i] = self._server_obs(next_states[i])
        self.states = next_states
        # one obs per stepped state: reuse the terminal obs of slots that kept going
        self._last_obs = np.stack(server_obs) if server_obs else self._obs(next_states)
        return self._last_obs, np.asarray(rewards, dtype=np.float32), dones, infos

    def terminal_obs(self, info: dict):
        if self.obs_mode == "state":
            return info["state"]
        if self._wants_server_obs():
            return np.asarray(info["terminal_obs"], dtype=np.float32)
        return self._obs_fn(info["state"]).astype(np.float32)

    def _obs(self, states):
        if self.obs_mode == "state":
            return states
        if self._wants_server_obs():
            return np.stack([self._server_obs(s) for s in states])
        return np.stack([self._obs_fn(s) for s in states]).astype(np.float32)

    @property
    def obs_dim(self) -> int:
        if self.obs_mode == "state":
            raise ValueError("state mode has no fixed obs dim")
        return int(np.prod(np.asarray(self._last_obs[0]).shape))

    def close(self):
        self._closed = True

    def __enter__(self):
        self._ensure_open()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()


# ------------------------------------------------------------------ models

def model_action(game: LocalGame, session, state: dict, owner: int = 0):
    """The platform's model protocol (gamekernel.models), run locally."""
    c = game.contract
    if c is None:
        raise ValueError(f"game {game.slug!r} declares no model contract")
    return kernel_models.model_action(
        game, c, lambda x: session.run(None, {session.get_inputs()[0].name: x})[0],
        state, owner, obs_modes=game.obs_modes)


def evaluate(model_path: str | Path, game: str | Path | LocalGame, *, episodes: int = 10,
             seed: int = 0, opponent: str | None = None, base_url: str = DEFAULT_BASE_URL,
             version: str | None = None, trust_remote_code: bool = False) -> dict:
    """Play ``episodes`` seeded games with an ONNX model, the way the server's
    model evaluation does (vs the default opponent when the game declares
    opponents, otherwise single-player score). Seeds are seed..seed+episodes-1,
    so two models evaluated with the same arguments face the same games."""
    try:
        import onnxruntime as ort
    except ImportError as e:  # pragma: no cover
        raise ImportError("evaluate needs onnxruntime: pip install onnxruntime") from e
    runtime = game if isinstance(game, LocalGame) else load_game(
        game, version, base_url=base_url, trust_remote_code=trust_remote_code)
    session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
    seeds = list(range(seed, seed + episodes))
    result = kernel_models.evaluate(
        runtime, runtime.meta, lambda state, owner: model_action(runtime, session, state, owner),
        seeds, opponent=opponent)
    return {"game": runtime.slug, "version": runtime.version,
            "seeds": [seeds[0], seeds[-1]], **result}


# ------------------------------------------------------------------ parity

def parity_check(game: str, *, base_url: str = DEFAULT_BASE_URL, seed: int = 0,
                 steps: int = 200, options: dict | None = None,
                 trust_remote_code: bool = False) -> dict:
    """Run one seeded episode locally and over OpenEnv with the same actions;
    report the first step whose full state differs (None when identical)."""
    from .remote import RemoteVecEnv
    local = LocalVecEnv(game, n=1, base_url=base_url, seed=seed, obs_mode="state",
                        new_options=options, autoreset=False,
                        trust_remote_code=trust_remote_code)
    with RemoteVecEnv(game=game, n=1, base_url=base_url, seed=seed, obs_mode="state",
                      new_options=options, autoreset=False) as remote:
        if remote.game_version != local.game_version:
            raise RuntimeError(f"server runs {remote.game_version}, "
                               f"local package is {local.game_version}")
        rng = np.random.default_rng(seed)
        for t in range(steps + 1):
            a, b = local.states[0], remote.states[0]
            if json.dumps(a, sort_keys=True) != json.dumps(b, sort_keys=True):
                return {"ok": False, "game": game, "version": local.game_version,
                        "steps": t, "mismatch_at": t}
            if t == steps or a.get("done"):
                return {"ok": True, "game": game, "version": local.game_version,
                        "steps": t, "mismatch_at": None}
            action = (int(rng.integers(local.num_actions))
                      if local.info.get("action_space", "").startswith("discrete")
                      else local.runtime.sample_action(a))
            local.step([action])
            remote.step([action])
