"""Tetris environment — stateless, deterministic, pure functions of the state.

Grid 10×20 (x right, y down), 7 tetrominoes, 4 actions:

    0 = left        (free move: no tick, reward 0)
    1 = right       (free move: no tick, reward 0)
    2 = rotate CW   (free move: no tick, reward 0, basic kicks)
    3 = hard drop   (locks the piece, tick+1)

Reward is only earned on hard drop:
    reward = step + (k*k) * line + (death if lockout)
with k = lines cleared by this lock (1/4/9/16 for 1/2/3/4 lines at defaults).

Pieces come from a 7-bag randomizer, deterministic per (seed, bag_idx):
two clients with the same seed see identical piece sequences and trajectories.
Game over ("lockout") when a new piece collides at spawn. Invalid free moves
are no-ops. Stepping a done state returns reward 0 / done true (snake-like).
"""
from __future__ import annotations

import random

import numpy as np

W, H = 10, 20
DEFAULT_REWARDS = {"line": 1.0, "step": -0.01, "death": -1.0}

# Piece rotations as cell offsets from the piece origin (x, y), y down.
# 0=I 1=O 2=T 3=S 4=Z 5=J 6=L. Rotation 0..3, clockwise (SRS-like boxes).
ROTATIONS: dict[int, list[list[tuple[int, int]]]] = {
    0: [[(0, 1), (1, 1), (2, 1), (3, 1)],   # I
        [(2, 0), (2, 1), (2, 2), (2, 3)],
        [(0, 2), (1, 2), (2, 2), (3, 2)],
        [(1, 0), (1, 1), (1, 2), (1, 3)]],
    1: [[(0, 0), (1, 0), (0, 1), (1, 1)]] * 4,  # O (rotation-invariant)
    2: [[(1, 0), (0, 1), (1, 1), (2, 1)],   # T
        [(1, 0), (1, 1), (2, 1), (1, 2)],
        [(0, 1), (1, 1), (2, 1), (1, 2)],
        [(1, 0), (0, 1), (1, 1), (1, 2)]],
    3: [[(1, 0), (2, 0), (0, 1), (1, 1)],   # S
        [(1, 0), (1, 1), (2, 1), (2, 2)],
        [(1, 1), (2, 1), (0, 2), (1, 2)],
        [(0, 0), (0, 1), (1, 1), (1, 2)]],
    4: [[(0, 0), (1, 0), (1, 1), (2, 1)],   # Z
        [(2, 0), (1, 1), (2, 1), (1, 2)],
        [(0, 1), (1, 1), (1, 2), (2, 2)],
        [(1, 0), (0, 1), (1, 1), (0, 2)]],
    5: [[(0, 0), (0, 1), (1, 1), (2, 1)],   # J
        [(1, 0), (2, 0), (1, 1), (1, 2)],
        [(0, 1), (1, 1), (2, 1), (2, 2)],
        [(1, 0), (1, 1), (0, 2), (1, 2)]],
    6: [[(2, 0), (0, 1), (1, 1), (2, 1)],   # L
        [(1, 0), (1, 1), (1, 2), (2, 2)],
        [(0, 1), (1, 1), (2, 1), (0, 2)],
        [(0, 0), (1, 0), (1, 1), (1, 2)]],
}

SPAWN_X = {0: 3, 1: 4, 2: 3, 3: 3, 4: 3, 5: 3, 6: 3}  # I 4-wide, O 2-wide, rest 3-wide
ROT_KICKS = [(0, 0), (-1, 0), (1, 0), (-2, 0), (2, 0), (0, -1)]  # basic kicks, no SRS

ACTION_NAMES = {0: "left", 1: "right", 2: "rotate", 3: "hard_drop"}


def cells_of(piece: dict) -> list[tuple[int, int]]:
    """Absolute board cells occupied by the piece."""
    x, y = piece["x"], piece["y"]
    return [(x + ox, y + oy) for ox, oy in ROTATIONS[piece["id"]][piece["rot"]]]


def collides(board: list[list[int]], piece: dict, dx: int = 0, dy: int = 0,
             rot: int | None = None) -> bool:
    """True if the piece (offset by dx/dy, rotation rot) hits wall/floor/stack."""
    r = piece["rot"] if rot is None else rot
    x, y = piece["x"] + dx, piece["y"] + dy
    for ox, oy in ROTATIONS[piece["id"]][r]:
        cx, cy = x + ox, y + oy
        if not (0 <= cx < W and 0 <= cy < H) or board[cy][cx]:
            return True
    return False


def shuffled_bag(seed: int, bag_idx: int) -> list[int]:
    """Deterministic 7-bag: same (seed, bag_idx) => same bag."""
    rnd = random.Random(f"{seed}:bag{bag_idx}")
    bag = list(range(7))
    rnd.shuffle(bag)
    return bag


def spawn_piece(piece_id: int) -> dict:
    return {"id": piece_id, "rot": 0, "x": SPAWN_X[piece_id], "y": 0}


def new_state(seed: int) -> dict:
    """Initial state: empty board + first piece from bag 0."""
    bag = shuffled_bag(seed, 0)
    piece = spawn_piece(bag[0])
    return {
        "board": [[0] * W for _ in range(H)],
        "piece": piece,
        "next": bag[1],
        "bag": bag,
        "bag_pos": 1,
        "bag_idx": 0,
        "score": 0,
        "lines": 0,
        "tick": 0,
        "seed": int(seed),
        "done": False,
        "cause": None,
        "grid": [W, H],
    }


def _clear_lines(board: list[list[int]]) -> tuple[list[list[int]], int]:
    kept = [row for row in board if any(cell == 0 for cell in row)]
    cleared = H - len(kept)
    return [[0] * W for _ in range(cleared)] + kept, cleared


def step_state(state: dict, action: int, rewards: dict | None = None) -> dict:
    """Advance one state by one action (0=left 1=right 2=rotate 3=hard_drop).

    Pure function. Returns the next state dict carrying reward / done.
    Free moves leave tick unchanged and reward 0; hard drop advances tick,
    locks the piece, clears lines and applies the line/step/death rewards.
    """
    rw = {**DEFAULT_REWARDS, **(rewards or {})}
    rw_line, rw_step, rw_death = float(rw["line"]), float(rw["step"]), float(rw["death"])

    piece = dict(state["piece"])
    board = [list(row) for row in state["board"]]
    out = {"grid": [W, H]}

    if state.get("done"):
        # like SnakeEnv::step on a done env: unchanged state, zero reward
        out.update(board=state["board"], piece=state["piece"], next=state["next"],
                   bag=state["bag"], bag_pos=state["bag_pos"], bag_idx=state["bag_idx"],
                   score=state["score"], lines=state["lines"], tick=state["tick"],
                   seed=state["seed"], done=True, cause=state.get("cause"),
                   reward=0.0)
        return out

    def fin(nboard, npiece, nnext, nbag, nbag_pos, nbag_idx,
            nscore, nlines, ntick, done, cause, reward):
        out.update(board=nboard, piece=npiece, next=nnext, bag=nbag,
                   bag_pos=nbag_pos, bag_idx=nbag_idx, score=nscore, lines=nlines,
                   tick=ntick, seed=state["seed"], done=done, cause=cause,
                   reward=reward)
        return out

    if action == 0:
        if not collides(board, piece, dx=-1):
            piece["x"] -= 1
            return fin(board, piece, state["next"], state["bag"],
                       state["bag_pos"], state["bag_idx"], state["score"],
                       state["lines"], state["tick"], False, None, 0.0)
        return fin(board, piece, state["next"], state["bag"], state["bag_pos"],
                   state["bag_idx"], state["score"], state["lines"], state["tick"],
                   False, None, 0.0)  # blocked by wall/stack: no-op
    if action == 1:
        if not collides(board, piece, dx=1):
            piece["x"] += 1
            return fin(board, piece, state["next"], state["bag"],
                       state["bag_pos"], state["bag_idx"], state["score"],
                       state["lines"], state["tick"], False, None, 0.0)
        return fin(board, piece, state["next"], state["bag"], state["bag_pos"],
                   state["bag_idx"], state["score"], state["lines"], state["tick"],
                   False, None, 0.0)  # blocked by wall/stack: no-op
    if action == 2:
        new_rot = (piece["rot"] + 1) % 4
        for dx, dy in ROT_KICKS:
            if not collides(board, piece, dx=dx, dy=dy, rot=new_rot):
                piece["x"] += dx
                piece["y"] += dy
                piece["rot"] = new_rot
                return fin(board, piece, state["next"], state["bag"],
                           state["bag_pos"], state["bag_idx"], state["score"],
                           state["lines"], state["tick"], False, None, 0.0)
        return fin(board, piece, state["next"], state["bag"], state["bag_pos"],
                   state["bag_idx"], state["score"], state["lines"], state["tick"],
                   False, None, 0.0)  # rotation blocked: no-op
    if action == 3:
        while not collides(board, piece, dy=1):
            piece["y"] += 1
        for cx, cy in cells_of(piece):
            board[cy][cx] = piece["id"] + 1  # 1..7 = locked, 0 = empty
        board, k = _clear_lines(board)
        score = state["score"] + k * k
        lines = state["lines"] + k
        tick = int(state["tick"]) + 1

        nid = state["bag"][state["bag_pos"]]          # consume "next"
        bag_pos = state["bag_pos"] + 1
        bag_idx, bag = state["bag_idx"], state["bag"]
        if bag_pos == 7:
            bag_pos = 0
            bag_idx += 1
            bag = shuffled_bag(state["seed"], bag_idx)
        nnext = bag[bag_pos]
        npiece = spawn_piece(nid)

        if collides(board, npiece):
            reward = rw_step + (k * k) * rw_line + rw_death
            return fin(board, npiece, nnext, bag, bag_pos, bag_idx,
                       score, lines, tick, True, "lockout", reward)
        reward = rw_step + (k * k) * rw_line
        return fin(board, npiece, nnext, bag, bag_pos, bag_idx,
                   score, lines, tick, False, None, reward)

    raise ValueError(f"action must be 0..3, got {action}")


def validate_state(state: dict) -> None:
    w, h = state.get("grid", [W, H])
    if [w, h] != [W, H]:
        raise ValueError(f"grid must be 10x20, got {w}x{h}")
    board = state["board"]
    if len(board) != H or any(len(row) != W for row in board):
        raise ValueError("board must be 20 rows x 10 cols")
    for row in board:
        for cell in row:
            if not isinstance(cell, int) or not (0 <= cell <= 7):
                raise ValueError(f"board cell {cell!r} must be an int in 0..7")
    piece = state["piece"]
    for key in ("id", "rot", "x", "y"):
        if key not in piece:
            raise ValueError(f"piece missing field {key}")
    if piece["id"] not in ROTATIONS:
        raise ValueError(f"bad piece id {piece['id']}")
    if piece["rot"] not in (0, 1, 2, 3):
        raise ValueError(f"bad rotation {piece['rot']}")
    if not isinstance(piece["x"], int) or not (-4 <= piece["x"] <= 10):
        # NOTE: x may be negative/≥9 after a rotation kick when the piece uses
        # the padding columns of its bounding box — the invariant that matters
        # is that every CELL is in bounds (checked below), not the origin.
        raise ValueError(f"piece x {piece['x']} out of range")
    if not isinstance(piece["y"], int) or not (-4 <= piece["y"] <= 20):
        raise ValueError(f"piece y {piece['y']} out of range")
    if not state.get("done"):
        # an active piece may never overlap locked cells (lockout pieces do,
        # but only in terminal states)
        for cx, cy in cells_of(piece):
            if not (0 <= cx < W and 0 <= cy < H) or board[cy][cx]:
                raise ValueError(f"active piece overlaps stack/board at ({cx},{cy})")
    if state["next"] not in ROTATIONS:
        raise ValueError(f"bad next piece id {state['next']}")
    bag = state["bag"]
    if (len(bag) != 7 or sorted(bag) != list(range(7))):
        raise ValueError("bag must be a permutation of 0..6")
    if not (0 <= state["bag_pos"] <= 6):
        raise ValueError("bag_pos out of range")
    if not isinstance(state["bag_idx"], int) or state["bag_idx"] < 0:
        raise ValueError("bag_idx must be a non-negative int")
    if not isinstance(state["seed"], int):
        raise ValueError("seed must be an int")
    for key in ("score", "lines", "tick"):
        if not isinstance(state[key], int) or state[key] < 0:
            raise ValueError(f"{key} must be a non-negative int")
    if state.get("cause") not in (None, "lockout"):
        raise ValueError(f"bad cause {state.get('cause')}")


def grid_obs(state: dict) -> np.ndarray:
    """2-channel 20x10 observation: ch0 locked cells (0/1), ch1 active piece (0/1)."""
    obs = np.zeros((2, H, W), dtype=np.float32)
    board = state["board"]
    for y in range(H):
        for x in range(W):
            obs[0, y, x] = 1.0 if board[y][x] else 0.0
    for cx, cy in cells_of(state["piece"]):
        if 0 <= cx < W and 0 <= cy < H:
            obs[1, cy, cx] = 1.0
    return obs
