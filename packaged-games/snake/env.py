"""Snake environment — pure-Python port of src/game.cpp + src/env.cpp.

Ported verbatim from the snake-web service (deploy/backend/env_api.py) so the
platform's /api/snake/env/* is bit-identical to https://snake.cree1p.com.

  - game rules (movement, growth, wall/self death, tail vacating)      game.cpp
  - relative action space (0=turn left, 1=straight, 2=turn right)      env.cpp rotate()
  - reward = reward_step + (reward_food if ate) + (reward_death if died)
  - padded 22x22x3 grid observation (ch0 hazard, ch1 head, ch2 food)   buildStateObs()

Everything is a PURE FUNCTION of the state dict — the server keeps no session
state. One HTTP request advances hundreds of envs in one batch.

Only deliberate difference from the C++ env: food spawn is deterministic
(random.Random((seed, tick)) instead of std::mt19937), so two clients with the
same seed see identical trajectories and results are reproducible.
"""
from __future__ import annotations

import random

import numpy as np

GRID_W, GRID_H = 20, 20
DIR_VEC = {0: (0, -1), 1: (0, 1), 2: (-1, 0), 3: (1, 0)}  # 0=up 1=down 2=left 3=right
_KCW = [0, 3, 1, 2]  # clockwise order on screen (y down): Up, Right, Down, Left

DEFAULT_REWARDS = {"food": 1.0, "step": -0.01, "death": -1.0}

INITIAL_BODY = [(10, 10), (9, 10), (8, 10)]
INITIAL_DIRECTION = 3  # right


def rotate(direction: int, action: int) -> int:
    """Relative action -> absolute direction. Same table as env.cpp::rotate."""
    if action == 1:
        return direction
    idx = _KCW.index(direction)
    return _KCW[(idx + (1 if action == 2 else 3)) % 4]  # 0=left, 2=right


def spawn_food(body, seed: int, tick: int, w: int = GRID_W, h: int = GRID_H):
    """Deterministic food spawn. Returns (food, win) where win means board full."""
    taken = set(body)
    free = [(x, y) for y in range(h) for x in range(w) if (x, y) not in taken]
    if not free:
        return None, True
    rnd = random.Random(f"{seed}:{tick}")  # str seed is supported and stable
    return free[rnd.randrange(len(free))], False


def new_state(seed: int, w: int = GRID_W, h: int = GRID_H) -> dict:
    """Initial state matching Game::reset() (plus deterministic first food)."""
    body = list(INITIAL_BODY)
    food, won = spawn_food(body, seed, 0, w, h)
    return {
        "body": body, "direction": INITIAL_DIRECTION, "food": food,
        "score": 0, "tick": 0, "seed": int(seed), "done": False,
        "cause": None, "grid": [w, h],
    }


def step_state(state: dict, action: int,
               rewards: dict | None = None) -> dict:
    """Advance one state by one relative action. Pure function; returns the
    next state dict plus reward/done/ate. Mirrors SnakeEnv::step + Game::step."""
    rw = {**DEFAULT_REWARDS, **(rewards or {})}
    rw_food, rw_step, rw_death = float(rw["food"]), float(rw["step"]), float(rw["death"])

    w, h = state.get("grid", [GRID_W, GRID_H])
    body = [tuple(p) for p in state["body"]]
    direction = state["direction"]
    food = tuple(state["food"]) if state["food"] else None
    seed = state["seed"]
    tick = int(state["tick"]) + 1
    out = {"grid": [w, h]}

    if state.get("done"):
        # C++ SnakeEnv::step on a done env returns {reward:0, done:true, ate:false}
        out.update(body=state["body"], direction=direction, food=state["food"],
                   score=state["score"], tick=state["tick"], seed=seed,
                   done=True, cause=state.get("cause"), reward=0.0, ate=False)
        return out

    d = rotate(direction, action)
    hx, hy = body[0]
    dx, dy = DIR_VEC[d]
    nh = (hx + dx, hy + dy)

    def fin(nbody, nfood, nscore, done, cause, reward, ate):
        out.update(body=nbody, direction=d, food=nfood,
                   score=nscore, tick=tick, seed=seed, done=done, cause=cause,
                   reward=reward, ate=ate)
        return out

    if not (0 <= nh[0] < w and 0 <= nh[1] < h):
        return fin(body, food, state["score"], True, "wall", rw_step + rw_death, False)

    growing = food is not None and nh == food
    limit = len(body) - (0 if growing else 1)  # tail vacates unless growing
    if nh in body[:limit]:
        return fin(body, food, state["score"], True, "self", rw_step + rw_death, False)

    nbody = [nh] + body
    nscore = state["score"]
    nfood = food
    won = False
    if growing:
        nscore += 1
        nfood, won = spawn_food(nbody, seed, tick, w, h)
        if won:
            # board full: body grew, game over (Win counts as death in reward)
            return fin(nbody, None, nscore, True, "win", rw_step + rw_death, True)
    else:
        nbody.pop()  # drop old tail

    reward = rw_step + (rw_food if growing else 0.0)
    return fin(nbody, nfood, nscore, False, None, reward, growing)


def grid_obs(body, food, w: int = GRID_W, h: int = GRID_H) -> np.ndarray:
    """Padded (w+2)x(h+2) x 3-channel observation, CxHxW float32.

    ch0 hazard: border walls + ALL body cells (head included)
    ch1 head
    ch2 food
    Identical layout to SnakeEnv::buildStateObs() (22x22 for a 20x20 board).
    """
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
    if food:
        obs[2, food[1] + 1, food[0] + 1] = 1.0
    return obs


def validate_state(state: dict, batch: bool = False) -> None:
    w, h = state.get("grid", [GRID_W, GRID_H])
    if [w, h] != [GRID_W, GRID_H]:
        raise ValueError(f"grid must be 20x20 (model-trained size), got {w}x{h}")
    body = state["body"]
    if len(body) < 2 or len(body) > w * h:
        raise ValueError(f"body length {len(body)} out of range")
    for x, y in body:
        if not (0 <= x < w and 0 <= y < h):
            raise ValueError(f"cell ({x},{y}) outside the board")
    if len({tuple(p) for p in body}) != len(body):
        raise ValueError("duplicate cells in body")
    if state["direction"] not in DIR_VEC:
        raise ValueError(f"bad direction {state['direction']}")
    if not isinstance(state["seed"], int):
        raise ValueError("seed must be an int")
    if state["food"] is not None:
        fx, fy = state["food"]
        if not (0 <= fx < w and 0 <= fy < h) or (fx, fy) in map(tuple, body):
            raise ValueError("food overlaps the snake or is out of bounds")
