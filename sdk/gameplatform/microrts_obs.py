"""microrts composite-action model I/O — must match backend/inference.py.

The c140 contract feeds the model a fixed (1,1546) input per idle unit per
tick: 6x16x16 grid channels from the acting owner's perspective + 10 unit
features. Train against these features and your exported model is plug-and-
play on the platform (PvE opponent / 模型代打 / 模型对战).

    from gameplatform.microrts_obs import unit_inputs
    for x in unit_inputs(state, owner=0):        # one row per idle unit
        logits = net(torch.from_numpy(x))        # (1,140)
"""
from __future__ import annotations

import numpy as np

H = W = 16
N_GRID = 6 * H * W   # 1536
N_UNIT = 10          # type one-hot(6) + x/15 + y/15 + hp/max + cd/5
N_FEAT = N_GRID + N_UNIT  # 1546

_TYPES = ["base", "barracks", "worker", "light", "heavy", "ranged"]
_UNIT_HP = {"base": 10, "barracks": 4, "worker": 1, "light": 4,
            "heavy": 10, "ranged": 2}


def grid_obs(state: dict, owner: int = 0) -> np.ndarray:
    """6x16x16 channels from `owner`'s perspective:
    ch0 walls, ch1 mines, ch2 my units, ch3 enemy units,
    ch4 my buildings, ch5 enemy buildings."""
    obs = np.zeros((6, H, W), dtype=np.float32)
    for y in range(H):
        for x in range(W):
            c = state["terrain"][y][x]
            if c == 1:
                obs[0, y, x] = 1.0
            elif c == 2:
                obs[1, y, x] = 1.0
    for u in state["units"]:
        mine = 2 if u["owner"] == owner else 3
        if u["type"] in ("base", "barracks"):
            mine += 2
        obs[mine, u["y"], u["x"]] = 1.0
    return obs


def unit_feats(state: dict, unit: dict) -> np.ndarray:
    f = np.zeros(N_UNIT, dtype=np.float32)
    f[_TYPES.index(unit["type"])] = 1.0
    f[6] = unit["x"] / 15.0
    f[7] = unit["y"] / 15.0
    f[8] = unit["hp"] / float(_UNIT_HP[unit["type"]])
    f[9] = (unit.get("cd") or 0) / 5.0
    return f


def unit_input(state: dict, owner: int, unit: dict) -> np.ndarray:
    """(1546,) float32 input for ONE unit's decision."""
    return np.concatenate([grid_obs(state, owner).reshape(-1),
                           unit_feats(state, unit)]).astype(np.float32)


def unit_inputs(state: dict, owner: int = 0, idle_only: bool = True) -> list:
    """Batch of (1546,) inputs for `owner`'s units, sorted by unit id
    (mirrors the server's per-unit polling order)."""
    out = []
    for u in sorted(state["units"], key=lambda u: u["id"]):
        if u["owner"] != owner:
            continue
        if idle_only and u.get("busy") is not None:
            continue
        out.append(unit_input(state, owner, u))
    return out
