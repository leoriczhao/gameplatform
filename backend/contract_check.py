"""Cross-check game.yaml contract.* against runtime info().schemas (A1).

One owner per fact: the package JSON Schemas exposed through OpenEnv own the
state/action/observation shapes; game.yaml contract.* is the model-hosting
declaration. When both describe the same thing they must agree, otherwise a
model exported against one silently drifts from the other. Registration
calls validate_contract(); a mismatch rejects the publish.

Packages that declare no contract are ignored. Shape checks only run when
the contract declares an obs_mode, so composite games whose model input is
not one of the observation modes (e.g. microrts) stay valid; their model
shape is still checked against the uploaded ONNX at model upload time.
"""
from __future__ import annotations

PROTOCOLS = ("simple", "composite")


def _shape(value) -> list[int] | None:
    """Return a positive-int shape list, or None when malformed."""
    if not isinstance(value, list) or not value:
        return None
    for dim in value:
        if not isinstance(dim, int) or isinstance(dim, bool) or dim <= 0:
            return None
    return list(value)


def _without_batch(shape: list[int]) -> list[int]:
    """Contract shapes carry a leading batch dim: [1, ...] -> [...]."""
    if len(shape) > 1 and shape[0] == 1:
        return shape[1:]
    return shape


def validate_contract(meta: dict, info: dict) -> None:
    """Raise ValueError when game.yaml contract.* contradicts info().schemas."""
    contract = (meta or {}).get("contract")
    if not isinstance(contract, dict) or not contract:
        return

    protocol = contract.get("protocol", "simple")
    if protocol not in PROTOCOLS:
        raise ValueError(
            f"contract.protocol must be one of {list(PROTOCOLS)}, got {protocol!r}")

    in_shape = contract.get("in_shape")
    out_shape = contract.get("out_shape")
    if in_shape is not None and _shape(in_shape) is None:
        raise ValueError("contract.in_shape must be a non-empty list of positive ints")
    if out_shape is not None and _shape(out_shape) is None:
        raise ValueError("contract.out_shape must be a non-empty list of positive ints")

    info = info if isinstance(info, dict) else {}
    # 与 OpenEnv 共用同一份 schema 生成（含旧包的兼容 fallback）
    from environment_contract import environment_schemas
    schemas = environment_schemas(info)
    obs_modes = list(info.get("obs_modes") or [])

    obs_mode = contract.get("obs_mode")
    if obs_mode is not None:
        if obs_mode not in obs_modes:
            raise ValueError(
                f"contract.obs_mode {obs_mode!r} is not in info().obs_modes {obs_modes}")
        observations = schemas.get("observations") or {}
        obs_schema = (observations.get(obs_mode)
                      if isinstance(observations, dict) else None)
        declared = obs_schema.get("x-shape") if isinstance(obs_schema, dict) else None
        if isinstance(declared, list) and in_shape is not None:
            want = _without_batch(_shape(in_shape) or [])
            if want != list(declared):
                raise ValueError(
                    f"contract.in_shape {in_shape} does not match "
                    f"schemas.observations[{obs_mode!r}].x-shape {declared}")

    action_schema = schemas.get("action") if isinstance(schemas, dict) else None
    if (protocol == "simple" and isinstance(action_schema, dict)
            and isinstance(action_schema.get("enum"), list)
            and out_shape is not None):
        actions = len(action_schema["enum"])
        if out_shape[-1] != actions:
            raise ValueError(
                f"contract.out_shape {out_shape} last dim must equal the "
                f"{actions} actions declared by schemas.action.enum")
