"""The platform's only model protocol, and the evaluation loop built on it.

A game's model face comes entirely from its package declaration
``meta.contract = {in_shape, out_shape, protocol: simple|composite, obs_mode?}``:

- simple:    obs(state, obs_mode) -> model -> argmax  (obs reshaped to in_shape)
- composite: model_inputs(state, owner) per-query inputs -> model each ->
             model_decode(outputs, state, owner)

The model runtime stays outside: callers pass ``run(x) -> y`` (an onnxruntime
session on the server and in the SDK).
"""
from __future__ import annotations

import numpy as np

SINGLE_MAX_STEPS = 2000
VERSUS_MAX_STEPS = 1500


def contract_of(meta: dict) -> dict | None:
    """The package's normalized contract; None when it declares none."""
    contract = (meta or {}).get("contract")
    if not isinstance(contract, dict):
        return None
    in_shape = tuple(contract.get("in_shape") or ())
    out_shape = tuple(contract.get("out_shape") or ())
    if not in_shape or not out_shape:
        return None
    return {"name": f"game.{meta.get('slug')}", "input": in_shape, "output": out_shape,
            "protocol": contract.get("protocol", "simple"),
            "obs_mode": contract.get("obs_mode")}


def model_action(game, contract: dict, run, state: dict, owner: int = 0, *,
                 obs_modes=()):
    """One action from a model for ``owner`` in ``state``."""
    if contract["protocol"] == "composite":
        inputs = game.model_inputs(state, owner)
        xs = [np.asarray(x, dtype=np.float32).reshape(contract["input"]) for x in inputs]
        # outputs cross the sandbox IPC as plain lists (ndarray is not JSON)
        outs = [np.asarray(run(x), dtype=np.float32).ravel().tolist() for x in xs]
        return game.model_decode(outs, state, owner)
    mode = contract.get("obs_mode") or (obs_modes[0] if obs_modes else None)
    obs = game.obs(state, mode)
    if obs is None:
        raise ValueError("game has no observation for models (obs returned None)")
    q = run(np.asarray(obs, dtype=np.float32).reshape(contract["input"]))[0]
    return int(np.argmax(q))


def evaluate(game, meta: dict, act, seeds, *, opponent: str | None = None) -> dict:
    """Play one game per seed with ``act(state, owner) -> action`` as p0.

    Games that declare ``opponents`` are played against a built-in strategy
    (``opponent``, else ``default_opponent``, else the first one) with the
    package's ``pvp.options``; others are scored single-player.
    """
    opponents = list(meta.get("opponents") or [])
    strategy = (opponent or meta.get("default_opponent") or opponents[0]) if opponents else None
    options = (meta.get("pvp") or {}).get("options") if opponents else None
    scores, lengths, wins = [], [], 0
    for seed in seeds:
        state = game.new_state(seed, options) if opponents else game.new_state(seed)
        for _ in range(VERSUS_MAX_STEPS if opponents else SINGLE_MAX_STEPS):
            if state.get("done"):
                break
            mine = act(state, 0)
            if opponents:
                theirs = game.opponent_action(state, {"type": "ai", "strategy": strategy})
                state = game.step_state(state, {"p0": mine, "p1": theirs})
            else:
                state = game.step_state(state, mine)
        if opponents and state.get("winner") == 0:
            wins += 1
        scores.append(float(state.get("score", state.get("reward", 0.0)) or 0.0))
        lengths.append(state.get("tick", 0))
    n = len(scores)
    metrics = {"episodes": n,
               "avg_score": round(sum(scores) / n, 2),
               "avg_length": round(sum(lengths) / n, 1),
               "scores": scores}
    if opponents:
        metrics.update(win_rate=round(wins / n, 2), opponent=strategy)
    return metrics
