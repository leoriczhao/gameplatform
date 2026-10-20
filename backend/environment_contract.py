"""Package-owned environment schemas and validated episode configuration.

Shared by OpenEnv and model-contract validation; no HTTP routing lives here.
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

def describe_environment(adapter, *, max_concurrent_envs: int) -> dict:
    info = dict(adapter.info() or {})
    info.pop("max_batch", None)  # internal worker batching is not a public API
    meta = getattr(adapter, "meta", None) or {}
    out = {**info, "game": adapter.game_id, "name": adapter.name,
           "schemas": environment_schemas(info), "meta": meta,
           "max_concurrent_envs": max_concurrent_envs}
    if meta.get("version") is not None:
        out["version"] = str(meta["version"])
    return out

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
