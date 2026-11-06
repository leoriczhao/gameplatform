"""One episode's rules: configuration checks, reset, step, reward and done.

Shared by the server's OpenEnv sessions and the SDK's LocalVecEnv. ``game``
is anything with the adapter call surface (a GameCalls, the server's
sandbox ProxyAdapter, or an SDK LocalGame).
"""
from __future__ import annotations

import math


def _tensor_schema(shape: list[int]) -> dict:
    schema: dict = {"type": "number"}
    for size in reversed(shape):
        schema = {"type": "array", "items": schema,
                  "minItems": size, "maxItems": size}
    schema["x-shape"] = shape
    schema["x-dtype"] = "float32"
    return schema


def environment_schemas(info: dict) -> dict:
    """Return package-owned schemas, with a safe fallback for legacy games."""
    supplied = info.get("schemas")
    if (isinstance(supplied, dict)
            and isinstance(supplied.get("state"), dict)
            and isinstance(supplied.get("action"), dict)
            and isinstance(supplied.get("observations", {}), dict)):
        return supplied

    action_schema: dict = {
        "description": "Game-specific JSON action; see actions/action_space"
    }
    actions = info.get("actions")
    if isinstance(actions, dict):
        try:
            values = sorted(int(key) for key in actions)
        except (TypeError, ValueError):
            pass
        else:
            action_schema = {"type": "integer", "enum": values}

    observations = {}
    modes = info.get("obs_modes") or []
    shape = info.get("obs_shape")
    for index, mode in enumerate(modes):
        observations[str(mode)] = (
            _tensor_schema(shape)
            if index == 0 and isinstance(shape, list)
            and all(isinstance(size, int) and size > 0 for size in shape)
            else {"description": f"Game-specific observation for mode {mode!r}"}
        )
    return {
        "state": {"type": "object", "additionalProperties": True,
                  "description": "Game-specific JSON state"},
        "action": action_schema,
        "observations": observations,
    }


def checked_rewards(info: dict, rewards: dict | None) -> dict:
    if rewards is not None and not isinstance(rewards, dict):
        raise ValueError("rewards must be an object")
    defaults = info.get("default_rewards") or {}
    result = {**defaults, **(rewards or {})}
    for key, value in result.items():
        if key not in defaults:
            raise ValueError(f"unknown reward key {key!r}")
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"reward {key!r} must be a number") from exc
        if not math.isfinite(number) or abs(number) > 1000:
            raise ValueError(f"reward {key!r} out of range [-1000, 1000]")
        result[key] = number
    return result


def resolve_obs_mode(info: dict, obs_mode: str | None) -> str | None:
    """None → the package's first mode; "state" → raw state (None)."""
    modes = info.get("obs_modes") or []
    if obs_mode is None:
        return modes[0] if modes else None
    if obs_mode == "state":
        return None
    if isinstance(obs_mode, str) and obs_mode in modes:
        return obs_mode
    raise ValueError(f"unknown obs_mode {obs_mode!r} (available: {list(modes) + ['state']})")


def coerce_reward(reward) -> float | None:
    if reward is None:
        return None
    try:
        return float(reward)
    except (TypeError, ValueError):
        return None


def check_reset_args(seed, options) -> None:
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError("seed must be a non-negative integer")
    if options is not None and not isinstance(options, dict):
        raise ValueError("options must be an object")


class Episode:
    """reset → step* for one game; rewards are fixed for the whole episode."""

    def __init__(self, game, info: dict, rewards: dict | None = None):
        self.game = game
        self.rewards = checked_rewards(info, rewards)
        self.state: dict | None = None
        self.step_count = 0

    def reset(self, seed: int, options: dict | None = None) -> dict:
        check_reset_args(seed, options)
        self.state = self.game.new_state(seed, options)
        self.step_count = 0
        return self.state

    @property
    def done(self) -> bool:
        return bool(self.state is not None and self.state.get("done", False))

    def step(self, action) -> tuple[dict, float | None, bool]:
        if self.state is None:
            raise ValueError("no active episode: reset first")
        self.game.validate_action(action, self.state)
        nxt = self.game.step_state(self.state, action, self.rewards)
        self.state = nxt
        self.step_count += 1
        return nxt, coerce_reward(nxt.get("reward", 0.0)), bool(nxt.get("done", False))
