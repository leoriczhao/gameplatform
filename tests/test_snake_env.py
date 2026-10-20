"""Snake env tests: behavior + bit-for-bit parity with the original service."""
import random
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, "/home/leoric/code/snake/deploy/backend")  # original env_api

import numpy as np
import pytest
import pkgload  # noqa: E402

try:
    import env_api as original  # noqa: E402 — deployed snake-web env module
except ImportError:  # CI 等没有 snake-web 源码的机器：只跳过逐位对照
    original = None
env = pkgload.load_submodule("snake", "env")  # 13 G3：种子包里的规则内核


def _greedy_random_states(module, seed, steps, action_rng):
    """Run a deterministic pseudo-random policy and return all states."""
    s = module.new_state(seed)
    states = [s]
    for _ in range(steps):
        a = action_rng.randrange(3)
        s = module.step_state(s, a)
        states.append(s)
        if s["done"]:
            break
    return states


@pytest.mark.skipif(original is None, reason="snake-web env_api 不在本机")
def test_bit_identical_to_original_service():
    """The port must advance EXACTLY like https://snake.cree1p.com's env."""
    for seed in (0, 1, 42, 1337, 2024):
        rng = random.Random(seed)
        ours = _greedy_random_states(env, seed, 600, rng)
        rng = random.Random(seed)
        theirs = _greedy_random_states(original, seed, 600, rng)
        assert len(ours) == len(theirs), f"seed {seed}: trajectory lengths differ"
        for i, (a, b) in enumerate(zip(ours, theirs)):
            assert a == b, f"seed {seed} step {i}: states diverge\n{a}\n{b}"


def test_determinism():
    a = env.new_state(7)
    b = env.new_state(7)
    assert a == b
    # full trajectory determinism:
    s1, s2 = env.new_state(9), env.new_state(9)
    for act in (1, 0, 1, 1, 2, 1, 0, 2):
        s1 = env.step_state(s1, act)
        s2 = env.step_state(s2, act)
    assert s1 == s2


def test_straight_ahead_wall_death():
    s = env.new_state(0)
    s["food"] = [0, 0]  # park food out of the way (seed-0 spawn may sit on the path)
    # head (10,10) heading right; 10 steps straight hits the right wall at x=19
    for _ in range(9):
        s = env.step_state(s, 1)
        assert not s["done"]
    s = env.step_state(s, 1)
    assert s["done"] and s["cause"] == "wall"
    assert s["score"] == 0
    # step + death rewards: -0.01 + -1.0
    assert abs(s["reward"] - (-1.01)) < 1e-9


def test_self_collision():
    # A 5-cell snake can coil a 2x2 loop into itself: up, left, up, right,
    # right, down -> the head lands on a body cell (tail too far away to vacate).
    s = env.new_state(0)
    s["body"] = [[10, 10], [9, 10], [8, 10], [7, 10], [7, 9]]
    s["food"] = [0, 0]  # park food far away so it can't interfere
    s = env.step_state(s, 0)  # -> heading up,    head (10,9)
    assert s["body"][0] == (10, 9) and not s["done"]
    s = env.step_state(s, 0)  # -> heading left,  head (9,9)
    assert s["body"][0] == (9, 9) and not s["done"]
    s = env.step_state(s, 2)  # -> heading up,    head (9,8)
    assert s["body"][0] == (9, 8) and not s["done"]
    s = env.step_state(s, 2)  # -> heading right, head (10,8)
    assert s["body"][0] == (10, 8) and not s["done"]
    s = env.step_state(s, 2)  # -> heading down,  head (10,9) -> on the body
    assert s["done"] and s["cause"] == "self", (s["done"], s["cause"])


def test_eating_grows_and_scores():
    # craft: food directly ahead of the head
    s = env.new_state(0)
    s["food"] = [11, 10]
    s = env.step_state(s, 1)  # straight into food
    assert s["ate"] is True
    assert s["score"] == 1
    assert len(s["body"]) == 4
    assert abs(s["reward"] - (1.0 - 0.01)) < 1e-9
    assert s["food"] is not None and s["food"] != (11, 10)


def test_done_state_step_returns_zero():
    s = env.new_state(0)
    for _ in range(10):
        s = env.step_state(s, 1)
    assert s["done"]
    nxt = env.step_state(s, 0)
    assert nxt["done"] and nxt["reward"] == 0.0 and nxt["ate"] is False
    assert nxt["body"] == s["body"] and nxt["tick"] == s["tick"]


def test_grid_obs_shape_and_content():
    s = env.new_state(0)
    obs = env.grid_obs(s["body"], s["food"])
    assert obs.shape == (3, 22, 22)
    # hazard border all ones
    assert obs[0, 0, :].all() and obs[0, -1, :].all()
    assert obs[0, :, 0].all() and obs[0, :, -1].all()
    # head channel marks the head
    hx, hy = s["body"][0]
    assert obs[1, hy + 1, hx + 1] == 1.0
    # food channel
    fx, fy = s["food"]
    assert obs[2, fy + 1, fx + 1] == 1.0


def test_validate_state_rejections():
    good = env.new_state(0)
    env.validate_state(good)  # ok
    cases = [
        ("bad grid", {**good, "grid": [10, 10]}),
        ("short body", {**good, "body": [[1, 1]]}),
        ("dup body", {**good, "body": [[1, 1], [1, 1]]}),
        ("bad direction", {**good, "direction": 9}),
        ("non-int seed", {**good, "seed": "42"}),
        ("food on body", {**good, "food": list(good["body"][0])}),
        ("food oob", {**good, "food": [99, 0]}),
    ]
    for label, state in cases:
        try:
            env.validate_state(state)
        except ValueError as e:
            assert str(e), label
        else:
            raise AssertionError(f"accepted bad state: {label}")
