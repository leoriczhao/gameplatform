"""Observation features for the remote env — vendored from python/features.py.

The original functions take a pybind11 env object; here a thin StateAdapter
wraps the full observation.state dict returned by the platform OpenEnv WS,
keeping the feature math byte-identical to the training repo.
"""
import numpy as np

# direction(): 0=Up, 1=Down, 2=Left, 3=Right
_HEADING = {0: (0, -1), 1: (0, 1), 2: (-1, 0), 3: (1, 0)}


class StateAdapter:
    """Mimics the snake_env.SnakeEnv accessors used by features.py."""

    def __init__(self, state: dict):
        self.state = state

    def grid_size(self):
        w, h = self.state.get("grid", [20, 20])
        return w, h

    def direction(self):
        return self.state["direction"]

    def head(self):
        return tuple(self.state["body"][0])

    def body(self):
        return [tuple(p) for p in self.state["body"]]

    def food(self):
        f = self.state["food"]
        return tuple(f) if f is not None else None


def relative_features(env) -> np.ndarray:
    """11-dim heading-relative features (same layout as python/features.py)."""
    w, h = env.grid_size()
    hx, hy = _HEADING[env.direction()]
    head = env.head()
    body = env.body()
    body_set = set(body)
    tail = body[-1]
    food = env.food()

    def in_grid(p):
        x, y = p
        return 0 <= x < w and 0 <= y < h

    def danger(p):
        return 1.0 if (not in_grid(p)) or p in body_set else 0.0

    ahead = (head[0] + hx, head[1] + hy)
    left = (head[0] + hy, head[1] - hx)
    right = (head[0] - hy, head[1] + hx)

    f = [danger(ahead), danger(right), danger(left)]

    if food is not None:
        dx = food[0] - head[0]
        dy = food[1] - head[1]
        rx = dx * hx + dy * hy          # forward component (>0 => ahead)
        ry = dy * hx - dx * hy          # >0 => to the right of heading
        f += [float(rx > 0), float(ry < 0), float(ry > 0)]
        f.append(float(min(1.0, (dx * dx + dy * dy) / float(w * w + h * h))))
    else:
        f += [0.0, 0.0, 0.0, 0.0]

    f += [float(tail == ahead), float(tail == right), float(tail == left)]
    f.append(float(len(body)) / float(w * h))
    return np.asarray(f, dtype=np.float32)


def rotated_window(env, R=4) -> np.ndarray:
    """(2R+1)x(2R+1)x3 local window centered on the head, rotation-normalized.

    Channels: [0] wall, [1] body (head excluded), [2] food.
    """
    w, h = env.grid_size()
    hx, hy = env.head()
    dirx, diry = _HEADING[env.direction()]
    leftx, lefty = diry, -dirx
    body_set = set(env.body())
    body_set.discard(env.head())
    food = env.food()
    K = 2 * R + 1
    win = np.zeros((K, K, 3), dtype=np.float32)
    for i in range(-R, R + 1):   # +i = forward (row 0 of the window)
        for j in range(-R, R + 1):  # +j = left of heading
            x = hx + i * dirx + j * leftx
            y = hy + i * diry + j * lefty
            if not (0 <= x < w and 0 <= y < h):
                win[R - i, j + R, 0] = 1.0
            elif (x, y) in body_set:
                win[R - i, j + R, 1] = 1.0
            elif food is not None and (x, y) == food:
                win[R - i, j + R, 2] = 1.0
    return win


def rotwin_features(env, R=4) -> np.ndarray:
    """rotwin obs = flattened rotated window + the 11 relative features."""
    win = rotated_window(env, R)
    return np.concatenate([win.reshape(-1), relative_features(env)]).astype(np.float32)


_CLEAR_H = 8
_ROOM_K = 8


def reachability_features(env, clear_h=_CLEAR_H, room_k=_ROOM_K) -> np.ndarray:
    """9-dim rotation-invariant obs aimed at self-boxing avoidance."""
    w, h = env.grid_size()
    hx, hy = env.head()
    dirx, diry = _HEADING[env.direction()]
    body = env.body()
    blocked = set(body)
    blocked.discard(body[-1])  # tail moves away -> passable

    def free(x, y):
        return 0 <= x < w and 0 <= y < h and (x, y) not in blocked

    def clearance(vx, vy):
        d = 0
        x, y = hx, hy
        while d < clear_h:
            x += vx
            y += vy
            if not free(x, y):
                break
            d += 1
        return d / clear_h

    right = (-diry, dirx)
    left = (diry, -dirx)

    f = [clearance(dirx, diry), clearance(*right), clearance(*left)]

    seen = {(hx, hy)}
    frontier = [(hx, hy)]
    for _ in range(room_k):
        nxt = []
        for x, y in frontier:
            for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if (nx, ny) not in seen and free(nx, ny):
                    seen.add((nx, ny))
                    nxt.append((nx, ny))
        frontier = nxt
    max_cells = 2 * room_k * room_k + 2 * room_k + 1
    f.append(len(seen) / max_cells)

    food = env.food()
    if food is not None:
        dx, dy = food[0] - hx, food[1] - hy
        rx = dx * dirx + dy * diry
        ry = dy * dirx - dx * diry
        f += [float(rx > 0), float(ry < 0), float(ry > 0),
              float(min(1.0, (dx * dx + dy * dy) / float(w * w + h * h)))]
    else:
        f += [0.0, 0.0, 0.0, 0.0]

    f.append(float(len(body)) / float(w * h))
    return np.asarray(f, dtype=np.float32)


def make_obs_fn(obs_mode: str, R: int = 4):
    if obs_mode == "features":
        return relative_features
    if obs_mode == "rotwin":
        return lambda env: rotwin_features(env, R)
    if obs_mode == "reach":
        return reachability_features
    raise ValueError(f"unknown feature obs mode {obs_mode!r}")


def grid_obs(body, food, w: int = 20, h: int = 20) -> np.ndarray:
    """Padded (w+2)x(h+2) x 3-channel grid, CxHxW — same layout as the server
    (ch0 hazard = walls + body incl. head, ch1 head, ch2 food). Lets clients
    compute terminal observations locally without an extra request."""
    pw, ph = w + 2, h + 2
    obs = np.zeros((3, ph, pw), dtype=np.float32)
    obs[0, 0, :] = 1.0
    obs[0, -1, :] = 1.0
    obs[0, :, 0] = 1.0
    obs[0, :, -1] = 1.0
    for x, y in body:
        obs[0, y + 1, x + 1] = 1.0
    hx, hy = body[0]
    obs[1, hy + 1, hx + 1] = 1.0
    if food is not None:
        fx, fy = food
        obs[2, fy + 1, fx + 1] = 1.0
    return obs
