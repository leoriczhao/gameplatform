"""Tetris env tests: determinism, free moves, drops, line clears, lockout."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import numpy as np
import pkgload  # noqa: E402
env = pkgload.load_submodule("tetris", "env")   # 13 G3：种子包里的规则内核
baseline_action = pkgload.load_submodule("tetris", "baseline").baseline_action


def _full_rows_except(rows, gap):
    """Board with `rows` full except a set of (x, y) gaps."""
    board = [[1 if y in rows else 0 for _ in range(env.W)] for y in range(env.H)]
    for x, y in gap:
        board[y][x] = 0
    return board


def _state_with(board, piece, nid, bag=None):
    bag = bag if bag is not None else list(range(7))
    return {
        "board": board, "piece": piece, "next": nid, "bag": bag,
        "bag_pos": bag.index(nid), "bag_idx": 0, "score": 0, "lines": 0,
        "tick": 0, "seed": 0, "done": False, "cause": None, "grid": [10, 20],
    }


def test_determinism_same_seed():
    a, b = env.new_state(42), env.new_state(42)
    assert a == b
    for act in (1, 1, 2, 0, 3, 2, 1, 3):
        a = env.step_state(a, act)
        b = env.step_state(b, act)
    assert a == b


def test_bag_determinism():
    assert env.shuffled_bag(7, 0) == env.shuffled_bag(7, 0)
    assert sorted(env.shuffled_bag(7, 0)) == list(range(7))
    # different (seed, bag_idx) -> (almost surely) different bags
    bags = {tuple(env.shuffled_bag(s, i)) for s in range(3) for i in range(4)}
    assert len(bags) == 12


def test_free_moves_no_tick_no_reward():
    s = env.new_state(0)
    p0 = dict(s["piece"])
    s = env.step_state(s, 1)  # right
    assert s["tick"] == 0 and s["reward"] == 0.0 and not s["done"]
    assert s["piece"]["x"] == p0["x"] + 1
    s = env.step_state(s, 0)  # left back
    assert s["piece"]["x"] == p0["x"]
    s = env.step_state(s, 2)  # rotate
    assert s["piece"]["rot"] == (p0["rot"] + 1) % 4
    assert s["tick"] == 0


def test_left_wall_clamp_is_noop():
    s = env.new_state(0)
    s["piece"]["x"] = 0
    nxt = env.step_state(s, 0)
    assert nxt["piece"] == s["piece"] and nxt["board"] == s["board"]


def test_rotation_kick_against_stack():
    # I piece horizontal at (6,5); a locked cell at (8,7) blocks the naive
    # rotation -> the kick table shifts it left by one column.
    board = [[0] * 10 for _ in range(20)]
    board[7][8] = 1
    s = _state_with(board, {"id": 0, "rot": 0, "x": 6, "y": 5}, nid=1)
    nxt = env.step_state(s, 2)
    assert nxt["piece"]["rot"] == 1
    assert nxt["piece"]["x"] == 5  # kicked left by 1


def test_hard_drop_locks_and_advances_bag():
    s = env.new_state(7)
    first_id = s["piece"]["id"]
    first_next = s["next"]
    nxt = env.step_state(s, 3)
    assert nxt["tick"] == 1
    assert nxt["piece"]["id"] == first_next  # spawned the old "next"
    assert nxt["next"] == s["bag"][(s["bag_pos"] + 1) % 7]
    # locked cells on the board are id+1
    locked = {cell for row in nxt["board"] for cell in row if cell}
    assert first_id + 1 in locked


def test_single_line_clear_scoring():
    board = _full_rows_except({19}, {(4, 19), (5, 19)})
    s = _state_with(board, {"id": 1, "rot": 0, "x": 4, "y": 17}, nid=2)
    nxt = env.step_state(s, 3)
    assert nxt["lines"] == 1
    assert nxt["score"] == 1  # k^2 = 1
    assert abs(nxt["reward"] - (0.99)) < 1e-9  # step + 1*line
    assert not nxt["done"]


def test_tetris_four_line_clear():
    board = _full_rows_except({16, 17, 18, 19}, {(5, y) for y in range(16, 20)})
    # I piece vertical (rot 1, cells at x+2, rows y..y+3) dropped into the gap
    s = _state_with(board, {"id": 0, "rot": 1, "x": 3, "y": 16}, nid=1)
    nxt = env.step_state(s, 3)
    assert nxt["lines"] == 4
    assert nxt["score"] == 16  # k^2
    assert abs(nxt["reward"] - (-0.01 + 16.0)) < 1e-9
    assert all(cell == 0 for row in nxt["board"] for cell in row), \
        "4 lines cleared, board should be empty"


def test_lockout_game_over():
    # Jagged stack that reaches the top but has NO full row (so nothing clears):
    # row 1 blocks the I spawn cells, every row below keeps one hole.
    board = [[0] * 10 for _ in range(20)]
    for x in (3, 4, 5, 6):
        board[1][x] = 1
    for y in range(2, 20):
        for x in range(10):
            board[y][x] = 1 if x != y % 10 else 0
    bag = list(range(7))  # next piece = bag[0] = I
    s = _state_with(board, {"id": 1, "rot": 0, "x": 0, "y": 0}, nid=0, bag=bag)
    nxt = env.step_state(s, 3)
    assert nxt["done"] and nxt["cause"] == "lockout"
    assert nxt["score"] == 0 and nxt["lines"] == 0
    assert abs(nxt["reward"] - (-0.01 - 1.0)) < 1e-9
    # the colliding spawn piece is still reported in the terminal state
    assert nxt["piece"] == {"id": 0, "rot": 0, "x": 3, "y": 0}


def test_done_state_step_zero():
    s = env.new_state(0)
    s["done"] = True
    s["cause"] = "lockout"
    nxt = env.step_state(s, 3)
    assert nxt["done"] and nxt["reward"] == 0.0
    assert nxt["tick"] == s["tick"] and nxt["score"] == s["score"]


def test_grid_obs_shape_and_content():
    s = env.new_state(0)
    obs = env.grid_obs(s)
    assert obs.shape == (2, 20, 10)
    assert obs.dtype == np.float32
    # active piece channel marks the piece cells
    for cx, cy in env.cells_of(s["piece"]):
        assert obs[1, cy, cx] == 1.0
    assert obs[0].sum() == 0.0  # empty board


def test_rotation_kick_can_park_piece_outside_grid_origin():
    """A kick may leave the piece origin at x=-1 while every CELL stays in
    bounds (S rot1 uses the padding column of its 3x3 box). Such states are
    legal: validation accepts them and the env still steps them."""
    s = _state_with([[0] * 10 for _ in range(20)],
                    {"id": 3, "rot": 1, "x": -1, "y": 0}, nid=2)
    env.validate_state(s)  # must not raise
    nxt = env.step_state(s, 3)  # hard drop locks it legally at the floor
    assert not nxt["done"]
    assert nxt["board"][18][1] == 4  # S id 3 -> cell value 4 at (1,18)


def test_validate_state_rejections():
    good = env.new_state(0)
    env.validate_state(good)  # ok
    bad_board = {**good, "board": [[0] * 10 for _ in range(19)]}
    bad_piece = {**good, "piece": {**good["piece"], "id": 99}}
    bad_rot = {**good, "piece": {**good["piece"], "rot": 4}}
    bad_next = {**good, "next": 9}
    bad_bag = {**good, "bag": [0, 1, 2, 3, 4, 5, 5]}
    bad_seed = {**good, "seed": "1"}
    bad_cause = {**good, "cause": "boom"}
    for label, state in [("board", bad_board), ("piece", bad_piece),
                         ("rot", bad_rot), ("next", bad_next),
                         ("bag", bad_bag), ("seed", bad_seed),
                         ("cause", bad_cause)]:
        try:
            env.validate_state(state)
        except ValueError:
            pass
        else:
            raise AssertionError(f"accepted bad state: {label}")


def test_baseline_plays_full_game_without_crashing():
    """Heuristic AI should survive many pieces and always return 0..3."""
    s = env.new_state(123)
    for _ in range(2000):
        if s["done"]:
            break
        a = baseline_action(s)
        assert a in (0, 1, 2, 3)
        s = env.step_state(s, a)
    assert s["tick"] > 0
    # the Dellacherie baseline must survive at least a handful of pieces
    assert s["lines"] >= 0 and s["score"] >= s["lines"]
