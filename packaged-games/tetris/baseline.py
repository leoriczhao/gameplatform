"""Heuristic baseline AI for Tetris (Dellacherie-style one-piece search).

For every reachable (rotation, x) placement, evaluate the resulting board with
aggregate height / holes / bumpiness / lines-cleared and pick the best. The
controller then emits the greedy free-move sequence (rotate -> move -> drop),
re-planning each step. Pure function of the state, deterministic.
"""
from __future__ import annotations

from .env import (H, W, ROTATIONS, ROT_KICKS, cells_of,
                  collides, _clear_lines)

# Classic Dellacherie weights.
W_AGG, W_HOLES, W_BUMP, W_LINES = -0.510066, -0.35663, -0.184483, 0.760666


def _rot_reachable(board, piece, target_rot):
    """Simulate the greedy rotate-until-match controller; return (ok, pos)."""
    p = dict(piece)
    for _ in range(3):
        if p["rot"] == target_rot:
            return True, p
        moved = False
        for dx, dy in ROT_KICKS:
            nr = (p["rot"] + 1) % 4
            if not collides(board, p, dx=dx, dy=dy, rot=nr):
                p["x"] += dx
                p["y"] += dy
                p["rot"] = nr
                moved = True
                break
        if not moved:
            return False, p
    return p["rot"] == target_rot, p


def _heights(board):
    hs = []
    for x in range(W):
        h = H
        for y in range(H):
            if board[y][x]:
                h = y
                break
        hs.append(h)
    return hs


def _eval(board, k):
    hs = _heights(board)
    agg = sum(H - h for h in hs)
    holes = 0
    for x in range(W):
        seen = False
        for y in range(H):
            if board[y][x]:
                seen = True
            elif seen:
                holes += 1
    bump = sum(abs(hs[i] - hs[i + 1]) for i in range(W - 1))
    return W_AGG * agg + W_HOLES * holes + W_BUMP * bump + W_LINES * k


def _place(board, piece_id, rot, x):
    """Drop the piece with (rot, x); return (board_after_clear, lines, final_y)
    or None if the placement is impossible."""
    p = {"id": piece_id, "rot": rot, "x": x, "y": 0}
    if collides(board, p):
        return None
    while not collides(board, p, dy=1):
        p["y"] += 1
    b = [row[:] for row in board]
    for cx, cy in cells_of(p):
        b[cy][cx] = piece_id + 1
    b, k = _clear_lines(b)
    return b, k, p["y"]


def best_placement(state):
    """Return (rot, x) of the best reachable placement (last resort: None)."""
    board, piece = state["board"], state["piece"]
    pid = piece["id"]
    candidates = []
    for target_rot in range(4):
        ok, _ = _rot_reachable(board, piece, target_rot)
        if not ok:
            continue
        rots = ROTATIONS[pid][target_rot]
        xmin = -min(ox for ox, _ in rots)
        xmax = W - 1 - max(ox for ox, _ in rots)
        for x in range(max(0, xmin), min(W - 1, xmax) + 1):
            res = _place(board, pid, target_rot, x)
            if res is None:
                continue
            b2, k, _ = res
            candidates.append((_eval(b2, k), k, x, target_rot))
    if not candidates:
        return None
    # highest eval, then most lines, then closest to center column (deterministic)
    candidates.sort(key=lambda c: (-c[0], -c[1], abs(c[2] - 4), c[3], c[2]))
    _, _, bx, brot = candidates[0]
    return brot, bx


def baseline_action(state) -> int:
    """Next greedy action (0=left 1=right 2=rotate 3=hard_drop) toward the
    best placement. Deterministic given the state."""
    if state.get("done"):
        return 3
    piece = state["piece"]
    target = best_placement(state)
    if target is None:
        return 3  # nothing placeable: drop and lose
    brot, bx = target
    if piece["rot"] != brot:
        return 2
    if piece["x"] < bx:
        return 1  # target is to the right
    if piece["x"] > bx:
        return 0  # target is to the left
    return 3
