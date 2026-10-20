"""Pure-numpy DQN inference for the built-in snake AI.

Ported verbatim from the snake-web service (deploy/backend/ai.py):
  - rotwin obs: rotated (2R+1)x(2R+1)x3 window centered on the head plus the
    11 heading-relative features (R=10 -> 1334 dims)
  - the MLP 1334 -> 128 -> 64 -> 3 forward pass (ReLU), weights loaded from an
    .npz exported by tools/export_model.py

No torch dependency on purpose: the container stays ~250MB instead of GBs.
"""
from __future__ import annotations

import numpy as np

GRID_W, GRID_H = 20, 20
WIN_R = 10
FEATURE_DIM = 11
OBS_DIM = (2 * WIN_R + 1) ** 2 * 3 + FEATURE_DIM  # 1334

# Direction encoding, same as src/game.h + python/features.py:
# 0=Up, 1=Down, 2=Left, 3=Right  (x right, y down)
HEADING = {0: (0, -1), 1: (0, 1), 2: (-1, 0), 3: (1, 0)}

# Relative actions, same as src/env.h: 0=turn left, 1=straight, 2=turn right.
ACTION_NAMES = {0: "left", 1: "straight", 2: "right"}

LAYER_KEYS = ["net.0.weight", "net.0.bias", "net.2.weight", "net.2.bias",
              "net.4.weight", "net.4.bias"]


class DQNPolicy:
    """Loaded MLP policy; forward(x) with x of shape (..., 1334)."""

    def __init__(self, npz_path: str):
        data = np.load(npz_path)
        self.w1 = data["net.0.weight"].astype(np.float32)
        self.b1 = data["net.0.bias"].astype(np.float32)
        self.w2 = data["net.2.weight"].astype(np.float32)
        self.b2 = data["net.2.bias"].astype(np.float32)
        self.w3 = data["net.4.weight"].astype(np.float32)
        self.b3 = data["net.4.bias"].astype(np.float32)
        assert self.w1.shape[1] == OBS_DIM, \
            f"model expects {self.w1.shape[1]} obs dims, code computes {OBS_DIM}"

    def forward(self, x: np.ndarray) -> np.ndarray:
        x = np.asarray(x, dtype=np.float32)
        h = np.maximum(x @ self.w1.T + self.b1, 0.0)
        h = np.maximum(h @ self.w2.T + self.b2, 0.0)
        return h @ self.w3.T + self.b3

    def argmax(self, x: np.ndarray) -> int:
        return int(np.argmax(self.forward(x), axis=-1))


def _relative_features(w: int, h: int, head, direction: int,
                       body_set: set, tail, food, body_len: int) -> np.ndarray:
    """Port of python/features.py::relative_features (11 dims)."""
    hx, hy = HEADING[direction]
    hxx, hyy = head

    def in_grid(p):
        return 0 <= p[0] < w and 0 <= p[1] < h

    def danger(p):
        return 1.0 if (not in_grid(p)) or p in body_set else 0.0

    ahead = (hxx + hx, hyy + hy)
    left = (hxx + hy, hyy - hx)
    right = (hxx - hy, hyy + hx)

    f = [danger(ahead), danger(right), danger(left)]

    if food is not None:
        dx, dy = food[0] - hxx, food[1] - hyy
        rx = dx * hx + dy * hy          # forward component (>0 => ahead)
        ry = dy * hx - dx * hy          # >0 => to the right of heading
        f += [float(rx > 0), float(ry < 0), float(ry > 0)]
        f.append(float(min(1.0, (dx * dx + dy * dy) / float(w * w + h * h))))
    else:
        f += [0.0, 0.0, 0.0, 0.0]

    f += [float(tail == ahead), float(tail == right), float(tail == left)]
    f.append(float(body_len) / float(w * h))
    return np.asarray(f, dtype=np.float32)


def rotwin_obs(body, direction: int, food, w: int = GRID_W, h: int = GRID_H) -> np.ndarray:
    """Port of python/features.py::rotwin_features(R=10) -> (1334,) float32.

    body: list/tuple of (x, y), body[0] is the head. food: (x, y) or None.
    """
    R = WIN_R
    hxx, hyy = body[0]
    dirx, diry = HEADING[direction]
    leftx, lefty = diry, -dirx  # same left convention as relative_features
    body_set = set(tuple(p) for p in body)
    body_set.discard(tuple(body[0]))  # center = head; keep body channel informative

    K = 2 * R + 1
    win = np.zeros((K, K, 3), dtype=np.float32)
    for i in range(-R, R + 1):        # +i = forward (row 0 of the window)
        for j in range(-R, R + 1):    # +j = left of heading
            x = hxx + i * dirx + j * leftx
            y = hyy + i * diry + j * lefty
            if not (0 <= x < w and 0 <= y < h):
                win[R - i, j + R, 0] = 1.0
            elif (x, y) in body_set:
                win[R - i, j + R, 1] = 1.0
            elif food is not None and (x, y) == tuple(food):
                win[R - i, j + R, 2] = 1.0

    rel = _relative_features(w, h, body[0], direction, body_set,
                             tuple(body[-1]), tuple(food) if food else None,
                             len(body))
    return np.concatenate([win.reshape(-1), rel]).astype(np.float32)


class SnakeAI:
    """One policy instance shared by the whole backend (stateless + thread-safe)."""

    def __init__(self, npz_path: str | None = None):
        # 包内资源随 __file__ 定位（沙箱禁 os，纯字符串处理）
        if npz_path is None:
            npz_path = __file__.rsplit("/", 1)[0] + "/weights.npz"
        self.policy = DQNPolicy(npz_path)

    def action(self, body, direction: int, food) -> tuple[int, list[float]]:
        obs = rotwin_obs(body, direction, food)
        q = self.policy.forward(obs)  # shape (3,)
        return int(np.argmax(q)), [float(v) for v in q]


# The action space is relative to the heading, so a reversal is impossible by
# construction (mirrors src/env.h comment).
DIRECTION_DELTA = {0: -1, 1: 0, 2: 1}  # action -> delta on direction index
