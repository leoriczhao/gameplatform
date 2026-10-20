"""Microrts env tests: determinism, economy, production, combat, win/loss,
two-agent mode, validation, and a full builtin-vs-builtin simulation."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import numpy as np
import pkgload  # noqa: E402
env = pkgload.load_submodule("microrts", "env")   # 13 G3：种子包里的规则内核
strategies = pkgload.load_submodule("microrts", "strategies")


def _unit(state, unit_id):
    for u in state["units"]:
        if u["id"] == unit_id:
            return u
    raise KeyError(unit_id)


def _hp(state, unit_id):
    """HP of a unit, 0 if it died this tick."""
    for u in state["units"]:
        if u["id"] == unit_id:
            return u["hp"]
    return 0


def _mk_state(seed=0, opponent="external", clear=True):
    s = env.new_state(seed, {"opponent": opponent})
    if clear:
        s["terrain"] = [[0] * 16 for _ in range(16)]
    return s


def _add_unit(s, owner, typ, x, y):
    u = env._make_unit(s["next_id"], owner, typ, x, y)
    s["next_id"] += 1
    s["units"].append(u)
    return u


def _step(s, cmds0, cmds1=None):
    if s["opponent"] == "external":
        action = {"p0": cmds0, "p1": cmds1 if cmds1 is not None else []}
    else:
        action = cmds0
    return env.step_state(s, action)


# ---------------------------------------------------------------- basic

def test_map_generation_deterministic():
    a, b = env.new_state(42), env.new_state(42)
    assert a == b
    terrain = a["terrain"]
    mines = sum(c == 2 for row in terrain for c in row)
    walls = sum(c == 1 for row in terrain for c in row)
    assert mines == 8 and walls == 4
    # spawn areas are clear
    for sx, sy in env.SPAWNS.values():
        for dx in range(-2, 3):
            for dy in range(-2, 3):
                cx, cy = sx + dx, sy + dy
                if 0 <= cx < 16 and 0 <= cy < 16:
                    assert terrain[cy][cx] == 0
    assert env.new_state(43)["terrain"] != terrain  # different seed, different map


def test_initial_state_contract():
    s = env.new_state(0)
    env.validate_state(s)
    assert s["tick"] == 0 and s["bank"] == [5, 5]  # MicroRTS starting gold
    assert s["damage"] == [0, 0]
    assert s["time_limit"] == 4000
    assert [u["type"] for u in s["units"]] == ["base", "base"]
    assert s["units"][0]["owner"] == 0 and s["units"][1]["owner"] == 1
    assert s["units"][0]["x"] == 1 and s["units"][0]["y"] == 1
    assert s["units"][1]["x"] == 14 and s["units"][1]["y"] == 14


def test_determinism_same_seed():
    rng = np.random.default_rng(7)
    s1, s2 = env.new_state(9, {"opponent": "worker_rush"}), \
        env.new_state(9, {"opponent": "worker_rush"})
    for _ in range(300):
        cmds = [[u["id"], 1, int(rng.integers(0, 4))]
                for u in s1["units"] if u["owner"] == 0 and u["busy"] is None]
        s1 = env.step_state(s1, cmds)
        s2 = env.step_state(s2, cmds)
        assert s1 == s2


# ---------------------------------------------------------------- economy

def test_harvest_and_return():
    s = _mk_state()
    s["terrain"][1][3] = 2  # mine at (3,1)
    w = _add_unit(s, 0, "worker", 2, 1)  # between base (1,1) and mine
    s1 = _step(s, [[w["id"], 2, 1]])  # harvest E -> mine at (3,1)
    assert _unit(s1, w["id"])["carry"] == 1
    assert s1["bank"] == [5, 5]
    s2 = _step(s1, [[w["id"], 3, 3]])  # return W -> base at (1,1) adjacent
    assert _unit(s2, w["id"])["carry"] == 0
    assert s2["bank"] == [6, 5]


def test_harvest_requires_adjacent_mine():
    s = _mk_state()
    s["terrain"][1][3] = 2
    w = _add_unit(s, 0, "worker", 2, 1)
    s1 = _step(s, [[w["id"], 2, 2]])  # dir S -> (2,2) is not a mine
    assert _unit(s1, w["id"])["carry"] == 0


def test_produce_worker():
    s = _mk_state()
    s["bank"] = [10, 0]
    base0 = s["units"][0]
    s1 = _step(s, [[base0["id"], 5, 1, "worker"]])
    assert s1["bank"] == [9, 0]  # cost 1 paid up front
    assert _unit(s1, base0["id"])["busy"]["remain"] == 49
    for _ in range(48):
        s1 = _step(s1, [])
    assert len(s1["units"]) == 2  # not yet (spawn at remain 0)
    s1 = _step(s1, [])
    assert len(s1["units"]) == 3
    w = [u for u in s1["units"] if u["type"] == "worker"][0]
    assert (w["x"], w["y"]) == (2, 1)  # E of the base


def test_unit_ids_stay_unique_across_productions():
    """Regression: next_id must advance or commands target the wrong units."""
    s = _mk_state()
    s["bank"] = [100, 0]
    base0 = s["units"][0]
    for i in range(3):
        # produce worker in a rotating direction to avoid cell blocks
        s = _step(s, [[base0["id"], 5, (i % 4), "worker"]])
        for _ in range(49):
            s = _step(s, [])
    ids = [u["id"] for u in s["units"]]
    assert len(ids) == len(set(ids)), f"duplicate ids: {ids}"
    assert sorted(ids) == [0, 1, 2, 3, 4]
    env.validate_state(s)  # full state must remain valid


def test_worker_builds_barracks():
    s = _mk_state()
    s["bank"] = [10, 0]
    w = _add_unit(s, 0, "worker", 2, 2)
    s1 = _step(s, [[w["id"], 4, 2, "barracks"]])  # S -> (2,3)
    assert s1["bank"] == [5, 0]
    for _ in range(98):
        s1 = _step(s1, [])
    assert all(u["type"] != "barracks" for u in s1["units"])
    s1 = _step(s1, [])
    b = [u for u in s1["units"] if u["type"] == "barracks"]
    assert len(b) == 1 and (b[0]["x"], b[0]["y"]) == (2, 3)
    assert b[0]["owner"] == 0


def test_produce_blocked_by_insufficient_gold():
    s = _mk_state()
    s["bank"] = [0, 0]  # starting gold removed
    base0 = s["units"][0]
    s1 = _step(s, [[base0["id"], 5, 1, "worker"]])  # bank 0 -> no-op
    assert s1["bank"] == [0, 0]
    assert _unit(s1, base0["id"])["busy"] is None


# ---------------------------------------------------------------- combat

def test_attack_damage_and_cooldown():
    s = _mk_state()
    a = _add_unit(s, 0, "light", 4, 4)
    b = _add_unit(s, 1, "light", 5, 4)
    s1 = _step(s, [[a["id"], 6, 1]])  # attack E
    assert _hp(s1, b["id"]) == 2  # light attack 2
    assert s1["damage"] == [2, 0]
    assert abs(s1["reward"] - 0.02) < 1e-9  # damage * 0.01
    for _ in range(3):  # cooldown: no damage on the next 3 ticks
        s1 = _step(s1, [[a["id"], 6, 1]])
        assert _hp(s1, b["id"]) == 2
    s1 = _step(s1, [[a["id"], 6, 1]])  # cd back to 0 on the 5th tick
    assert _hp(s1, b["id"]) == 0
    assert all(u["id"] != b["id"] for u in s1["units"])  # dead unit removed


def test_ranged_attacks_at_distance():
    s = _mk_state()
    a = _add_unit(s, 0, "ranged", 4, 4)
    b = _add_unit(s, 1, "worker", 7, 4)  # distance 3 = ranged range
    s1 = _step(s, [[a["id"], 6, 1]])
    assert _hp(s1, b["id"]) == 0  # worker hp 1, ranged attack 1
    s = _mk_state()
    a = _add_unit(s, 0, "ranged", 4, 4)
    b = _add_unit(s, 1, "worker", 8, 4)  # distance 4: out of range
    s1 = _step(s, [[a["id"], 6, 1]])
    assert _hp(s1, b["id"]) == 1


def test_move_blocked_by_wall_and_unit():
    s = _mk_state()
    s["terrain"][1][5] = 1  # wall at (5,1)
    w = _add_unit(s, 0, "worker", 4, 1)
    w2 = _add_unit(s, 0, "worker", 3, 1)
    s1 = _step(s, [[w["id"], 1, 1]])  # E into wall -> no move
    assert (_unit(s1, w["id"])["x"], _unit(s1, w["id"])["y"]) == (4, 1)
    s2 = _step(s, [[w["id"], 1, 3]])  # W into another unit -> no move
    assert (_unit(s2, w["id"])["x"], _unit(s2, w["id"])["y"]) == (4, 1)


def test_elimination_win():
    s = _mk_state()
    a = _add_unit(s, 0, "heavy", 13, 14)  # next to enemy base (14,14)
    base1 = s["units"][1]
    # heavy attack 4 vs base hp 10 -> dead on the 3rd hit (ticks 1, 5, 9)
    for _ in range(9):
        s = _step(s, [[a["id"], 6, 1]])
        if s["done"]:
            break
    assert s["done"] and s["cause"] == "eliminated" and s["winner"] == 0
    assert all(u["owner"] != 1 for u in s["units"])
    assert s["damage"] == [10, 0]  # cumulative: 4 + 4 + 2
    # terminal tick reward: this tick's damage (2) * 0.01 + win 1.0
    assert abs(s["reward"] - 1.02) < 1e-9


def test_time_limit_and_damage_tiebreak():
    s = _mk_state()
    s["tick"] = 3999
    s1 = _step(s, [])
    assert s1["done"] and s1["cause"] == "time" and s1["winner"] is None
    s["damage"] = [7, 3]
    s2 = _step(s, [])
    assert s2["winner"] == 0


def test_done_state_step_returns_zero():
    s = _mk_state()
    s["done"] = True
    s["winner"] = 0
    s["cause"] = "eliminated"
    nxt = env.step_state(s, [])
    assert nxt["reward"] == 0.0 and nxt["done"] and nxt["tick"] == s["tick"]


# ---------------------------------------------------------------- two agent

def test_external_mode_both_players_act():
    s = _mk_state(opponent="external")
    s["bank"] = [10, 10]
    base0, base1 = s["units"][0], s["units"][1]
    action = {"p0": [[base0["id"], 5, 1, "worker"]],
              "p1": [[base1["id"], 5, 3, "worker"]]}
    s = env.step_state(s, action)
    assert s["bank"] == [9, 9]
    for _ in range(49):
        s = env.step_state(s, {"p0": [], "p1": []})
    workers = [u for u in s["units"] if u["type"] == "worker"]
    assert len(workers) == 2
    assert {w["owner"] for w in workers} == {0, 1}


# ---------------------------------------------------------------- validation

def test_validate_action_rejections():
    s = _mk_state(opponent="external")
    base0, base1 = s["units"][0], s["units"][1]
    cases = [
        ([[base0["id"], 9, 1]], "bad command code"),
        ([[base0["id"], 1, 4]], "bad direction"),
        ([[base1["id"], 1, 1]], "foreign unit commanded by p0"),
        ([[999, 1, 1]], "unknown unit id"),
        ([[base0["id"], 5, 1, "light"]], "base cannot produce light"),
        ([[base0["id"], 4, 1, "barracks"]], "base cannot build"),
    ]
    for action, label in cases:
        try:
            env.validate_action(s, action)
        except ValueError:
            pass
        else:
            raise AssertionError(f"accepted bad action: {label}")
    # wrong shape for the mode
    try:
        env.validate_action(s, [[base0["id"], 1, 1]])  # external needs p0/p1
    except ValueError:
        pass
    else:
        raise AssertionError("accepted list action in external mode")
    s2 = _mk_state(opponent="worker_rush")
    try:
        env.validate_action(s2, {"p0": [], "p1": []})  # builtin mode needs list
    except ValueError:
        pass
    else:
        raise AssertionError("accepted dict action in builtin mode")


def test_validate_state_rejections():
    good = env.new_state(0)
    env.validate_state(good)
    bad_terrain = {**good, "terrain": good["terrain"][:15]}
    bad_unit = {**good, "units": [{**good["units"][0], "hp": 99}]}
    bad_owner = {**good, "units": [{**good["units"][0], "owner": 2}]}
    bad_bank = {**good, "bank": [0]}
    bad_opponent = {**good, "opponent": "skynet"}
    for label, st in [("terrain", bad_terrain), ("hp", bad_unit),
                      ("owner", bad_owner), ("bank", bad_bank),
                      ("opponent", bad_opponent)]:
        try:
            env.validate_state(st)
        except ValueError:
            pass
        else:
            raise AssertionError(f"accepted bad state: {label}")


def test_unknown_opponent_rejected_at_new():
    try:
        env.new_state(0, {"opponent": "skynet"})
    except ValueError:
        pass
    else:
        raise AssertionError("accepted unknown opponent")


def test_grid_obs_shape_and_channels():
    s = env.new_state(0)
    obs = env.grid_obs(s)
    assert obs.shape == (6, 16, 16)
    assert obs.dtype == np.float32
    assert obs[1].sum() == 8  # mines
    assert obs[0].sum() == 4  # walls
    assert obs[4, 1, 1] == 1.0  # my base channel
    assert obs[5, 14, 14] == 1.0  # enemy base channel


# ---------------------------------------------------------------- simulation

def test_full_game_worker_rush_vs_light_rush():
    s = env.new_state(123, {"opponent": "external"})
    s["time_limit"] = 800  # keep the test fast
    for _ in range(800):
        if s["done"]:
            break
        a = {"p0": strategies.builtin_commands("worker_rush", s, 0),
             "p1": strategies.builtin_commands("light_rush", s, 1)}
        s = env.step_state(s, a)
    assert s["done"]
    assert s["cause"] in ("eliminated", "time")
    assert s["winner"] in (0, 1, None)
    # with starting gold the game must actually develop (no economy deadlock)
    assert sum(s["damage"]) > 0 or s["cause"] == "eliminated"
    assert s["tick"] <= 800


def test_builtin_strategies_are_deterministic():
    s1 = env.new_state(5, {"opponent": "worker_rush"})
    s2 = env.new_state(5, {"opponent": "worker_rush"})
    for _ in range(100):
        c1 = strategies.builtin_commands("worker_rush", s1, 1)
        c2 = strategies.builtin_commands("worker_rush", s2, 1)
        assert c1 == c2
        s1 = env.step_state(s1, [])
        s2 = env.step_state(s2, [])
