"""MicroRTS — a platform port of the MicroRTS rules (Ontanon, 2013).

MicroRTS is a minimalist RTS used for AI research (annual IEEE CoG competition,
gym-microrts, dozens of published bots). This is a faithful-but-simplified
Python port tuned for the platform's stateless batch env contract.

Board: 16x16 grid. Terrain: empty / wall / gold mine. Two players (0 and 1)
start with one Base. Units harvest gold, build/produce, move and fight.

Design notes vs the original Java engine:
  - tick-based: every tick each unit may execute ONE command (durations in
    ticks: move/harvest/return/attack = 1, produce/build = 50..120)
  - simultaneous-ish resolution: moves resolve in unit-id order (deterministic)
  - damage applies at the end of the tick, deaths removed then (simultaneous)
  - win: destroy every enemy unit; time limit 4000 ticks -> higher damage wins

Two play modes (state["opponent"]):
  - built-in strategy ("worker_rush" | "light_rush" | "ranged_rush"): the env
    runs the opponent's policy inside step_state; the API action is the
    commands of player 0's units only (single-agent, like snake/tetris)
  - "external": both players are external; the API action is
    {"p0": [cmds], "p1": [cmds]}

Commands (per unit, one per tick): [unit_id, cmd] + optional dir/type
  0 wait | 1 move(dir) | 2 harvest(dir) | 3 return(dir) |
  4 build(dir, "barracks") | 5 produce(dir, "worker"|"light"|"heavy"|"ranged") |
  6 attack(dir)
dir: 0=N 1=E 2=S 3=W (y down). Busy units ignore new commands.

Everything is a pure function of the state dict; the map (walls/mines) is
deterministic per (seed, "map"), same seed => same trajectory.
"""
from __future__ import annotations

import random

import numpy as np

W, H = 16, 16
TIME_LIMIT = 4000
ATTACK_CD = 4
CARRY_CAP = 1

DEFAULT_REWARDS = {"win": 1.0, "loss": -1.0, "damage": 0.01}

# 0=empty 1=wall 2=gold mine
TERRAIN_NAMES = {0: "empty", 1: "wall", 2: "mine"}

# unit type -> {hp, attack, range}
UNIT_STATS = {
    "base":     {"hp": 10, "attack": 0, "range": 0},
    "barracks": {"hp": 4,  "attack": 0, "range": 0},
    "worker":   {"hp": 1,  "attack": 1, "range": 1},
    "light":    {"hp": 4,  "attack": 2, "range": 1},
    "heavy":    {"hp": 10, "attack": 4, "range": 1},
    "ranged":   {"hp": 2,  "attack": 1, "range": 3},
}

# producer type -> {unit_type: (gold cost, duration in ticks)}
PRODUCE = {
    "base":     {"worker": (1, 50)},
    "barracks": {"light": (2, 80), "heavy": (3, 120), "ranged": (2, 100)},
}
# worker build: {unit_type: (gold cost, duration)}
WORKER_BUILD = {"barracks": (5, 100)}

SPAWNS = {0: (1, 1), 1: (W - 2, H - 2)}
BUILTIN_OPPONENTS = ("worker_rush", "light_rush", "ranged_rush")

DIRS = {0: (0, -1), 1: (1, 0), 2: (0, 1), 3: (-1, 0)}  # N E S W (y down)
CMD_NAMES = {0: "wait", 1: "move", 2: "harvest", 3: "return",
             4: "build", 5: "produce", 6: "attack"}


def _make_unit(unit_id: int, owner: int, typ: str, x: int, y: int) -> dict:
    return {"id": unit_id, "owner": owner, "type": typ, "x": x, "y": y,
            "hp": UNIT_STATS[typ]["hp"], "carry": 0, "cd": 0, "busy": None}


def gen_map(seed: int) -> list[list[int]]:
    """Deterministic 16x16 map: 8 gold mines + 4 walls, clear around spawns."""
    rnd = random.Random(f"{seed}:map")
    terrain = [[0] * W for _ in range(H)]
    blocked = set()
    for sx, sy in SPAWNS.values():
        for dx in range(-2, 3):
            for dy in range(-2, 3):
                cx, cy = sx + dx, sy + dy
                if 0 <= cx < W and 0 <= cy < H:
                    blocked.add((cx, cy))
    mines = 0
    while mines < 8:
        x, y = rnd.randrange(W), rnd.randrange(H)
        if (x, y) in blocked or terrain[y][x] != 0:
            continue
        terrain[y][x] = 2
        blocked.add((x, y))
        mines += 1
    walls = 0
    while walls < 4:
        x, y = rnd.randrange(W), rnd.randrange(H)
        if (x, y) in blocked or terrain[y][x] != 0:
            continue
        terrain[y][x] = 1
        walls += 1
    return terrain


def new_state(seed: int, options: dict | None = None) -> dict:
    """Initial state: one base per player + deterministic map."""
    options = options or {}
    opponent = options.get("opponent", "worker_rush")
    if opponent not in BUILTIN_OPPONENTS and opponent != "external":
        raise ValueError(f"unknown opponent {opponent!r} "
                         f"(builtin: {list(BUILTIN_OPPONENTS)} or 'external')")
    seed = int(seed)
    units = []
    for owner in (0, 1):
        x, y = SPAWNS[owner]
        units.append(_make_unit(len(units), owner, "base", x, y))
    return {
        "grid": [W, H],
        "terrain": gen_map(seed),
        "units": units,
        "bank": [5, 5],  # MicroRTS initial gold: the economy can start
        "tick": 0,
        "seed": seed,
        "time_limit": TIME_LIMIT,
        "done": False,
        "winner": None,
        "cause": None,
        "damage": [0, 0],
        "opponent": opponent,
        "players": 2,
        "next_id": len(units),
    }


# ---------------------------------------------------------------- helpers

def _at(state: dict, x: int, y: int) -> dict | None:
    for u in state["units"]:
        if u["x"] == x and u["y"] == y:
            return u
    return None


def _free(state: dict, x: int, y: int) -> bool:
    return (0 <= x < W and 0 <= y < H and state["terrain"][y][x] != 1
            and _at(state, x, y) is None)


def _adjacent(state: dict, x: int, y: int, owner: int, typ: str) -> bool:
    for dx, dy in DIRS.values():
        u = _at(state, x + dx, y + dy)
        if u and u["owner"] == owner and u["type"] == typ:
            return True
    return False


def _first_enemy_in_dir(state: dict, unit: dict, d: int):
    """Nearest enemy unit in direction d within the unit's range."""
    dx, dy = DIRS[d]
    rng = UNIT_STATS[unit["type"]]["range"]
    x, y = unit["x"], unit["y"]
    for step in range(1, rng + 1):
        u = _at(state, x + dx * step, y + dy * step)
        if u and u["owner"] != unit["owner"]:
            return u
    return None


def _spawn_check(state: dict, unit: dict, d: int) -> bool:
    x, y = unit["x"] + DIRS[d][0], unit["y"] + DIRS[d][1]
    return _free(state, x, y)


# ---------------------------------------------------------------- commands

def _issue(state: dict, unit: dict, cmd: int, d: int, typ: str,
           damage: list) -> None:
    """Resolve one command issued by `unit` this tick (see module docstring)."""
    if cmd == 0:  # wait
        return
    if cmd == 1:  # move
        x, y = unit["x"] + DIRS[d][0], unit["y"] + DIRS[d][1]
        if _free(state, x, y):
            unit["x"], unit["y"] = x, y
            unit["busy"] = {"cmd": cmd, "dir": d, "remain": 1}
        return
    if cmd == 2:  # harvest (worker)
        if unit["type"] != "worker":
            return
        x, y = unit["x"] + DIRS[d][0], unit["y"] + DIRS[d][1]
        if (0 <= x < W and 0 <= y < H and state["terrain"][y][x] == 2
                and unit["carry"] < CARRY_CAP):
            unit["carry"] += 1
            unit["busy"] = {"cmd": cmd, "dir": d, "remain": 1}
        return
    if cmd == 3:  # return (worker)
        if unit["type"] != "worker" or unit["carry"] <= 0:
            return
        if _adjacent(state, unit["x"], unit["y"], unit["owner"], "base"):
            state["bank"][unit["owner"]] += unit["carry"]
            unit["carry"] = 0
            unit["busy"] = {"cmd": cmd, "dir": d, "remain": 1}
        return
    if cmd == 4:  # build (worker -> barracks)
        if unit["type"] != "worker" or typ not in WORKER_BUILD:
            return
        cost, dur = WORKER_BUILD[typ]
        if state["bank"][unit["owner"]] < cost or not _spawn_check(state, unit, d):
            return
        state["bank"][unit["owner"]] -= cost
        unit["busy"] = {"cmd": cmd, "dir": d, "type": typ, "remain": dur}
        return
    if cmd == 5:  # produce
        table = PRODUCE.get(unit["type"], {})
        if typ not in table:
            return
        cost, dur = table[typ]
        if state["bank"][unit["owner"]] < cost or not _spawn_check(state, unit, d):
            return
        state["bank"][unit["owner"]] -= cost
        unit["busy"] = {"cmd": cmd, "dir": d, "type": typ, "remain": dur}
        return
    if cmd == 6:  # attack
        if UNIT_STATS[unit["type"]]["attack"] <= 0 or unit["cd"] > 0:
            return
        target = _first_enemy_in_dir(state, unit, d)
        if target is None:
            return
        dmg = UNIT_STATS[unit["type"]]["attack"]
        damage.append((target["id"], dmg, unit["owner"]))
        unit["cd"] = ATTACK_CD
        unit["busy"] = {"cmd": cmd, "dir": d, "remain": 1}
        return


def _tick_busy(state: dict, next_id: list) -> None:
    """Count down busy counters; complete productions at 0. If the planned
    spawn cell is blocked, re-pick any free adjacent cell (deterministic
    N E S W order) — production always completes into free space."""
    for u in state["units"]:
        if u["cd"] > 0:
            u["cd"] -= 1
        b = u["busy"]
        if b is None:
            continue
        if b["remain"] > 0:
            b["remain"] -= 1
        if b["remain"] == 0 and b["cmd"] in (4, 5):
            if _spawn_check(state, u, b["dir"]):
                x, y = u["x"] + DIRS[b["dir"]][0], u["y"] + DIRS[b["dir"]][1]
                state["units"].append(
                    _make_unit(next_id[0], u["owner"], b["type"], x, y))
                next_id[0] += 1
                u["busy"] = None
            else:
                # blocked: switch to any other free adjacent cell and retry
                newd = next((d for d in sorted(DIRS)
                             if _spawn_check(state, u, d)), None)
                if newd is not None:
                    b["dir"] = newd
                # no free cell anywhere: stay busy at remain 0
        elif b["remain"] == 0:
            u["busy"] = None


def _apply_damage(state: dict, damage: list) -> list[int]:
    """Apply the tick's attacks, remove dead units, return damage dealt per
    owner (applied HP, not raw attack values)."""
    by_id = {u["id"]: u for u in state["units"]}
    dealt_by = [0, 0]
    for target_id, dmg, attacker_owner in damage:
        t = by_id.get(target_id)
        if t is None:
            continue
        dealt = min(dmg, t["hp"])
        t["hp"] -= dealt
        state["damage"][attacker_owner] += dealt
        dealt_by[attacker_owner] += dealt
    state["units"] = [u for u in state["units"] if u["hp"] > 0]
    return dealt_by


def _check_done(state: dict) -> None:
    if state["done"]:
        return
    alive = [u for u in state["units"]]
    owners = {u["owner"] for u in alive}
    if 0 not in owners or 1 not in owners:
        state["done"] = True
        state["cause"] = "eliminated"
        state["winner"] = next(iter(owners)) if owners else None
        return
    if state["tick"] >= state["time_limit"]:
        state["done"] = True
        state["cause"] = "time"
        if state["damage"][0] != state["damage"][1]:
            state["winner"] = 0 if state["damage"][0] > state["damage"][1] else 1
        else:
            state["winner"] = None  # draw


# ---------------------------------------------------------------- step

def step_state(state: dict, action, rewards: dict | None = None) -> dict:
    """Advance one tick. Single-agent mode: `action` = commands for player 0's
    units (opponent moves are generated by the built-in strategy). External
    mode: `action` = {"p0": [cmds], "p1": [cmds]}. Pure function."""
    rw = {**DEFAULT_REWARDS, **(rewards or {})}
    rw_win, rw_loss, rw_damage = (float(rw["win"]), float(rw["loss"]),
                                   float(rw["damage"]))

    units = [dict(u) for u in state["units"]]
    for u in units:
        if u["busy"] is not None:
            u["busy"] = dict(u["busy"])
    nxt = {
        "grid": [W, H], "terrain": [list(r) for r in state["terrain"]],
        "units": units, "bank": list(state["bank"]), "tick": state["tick"],
        "seed": state["seed"], "time_limit": state["time_limit"],
        "done": state["done"], "winner": state["winner"],
        "cause": state["cause"], "damage": list(state["damage"]),
        "opponent": state["opponent"], "players": 2,
        "next_id": state["next_id"],
    }

    if state.get("done"):
        nxt["reward"] = 0.0
        return nxt

    # resolve the two players' command lists
    if state["opponent"] == "external":
        cmds0 = action["p0"]
        cmds1 = action["p1"]
    else:
        cmds0 = action
        from . import strategies
        cmds1 = strategies.builtin_commands(state["opponent"], nxt, owner=1)

    by_id = {u["id"]: u for u in units}
    damage: list = []

    def run(cmds, owner):
        for entry in cmds:
            unit_id, cmd = int(entry[0]), int(entry[1])
            u = by_id.get(unit_id)
            if u is None or u["owner"] != owner or u["busy"] is not None:
                continue  # unknown/foreign/busy -> ignore (deterministic)
            d = int(entry[2]) if len(entry) > 2 else 0
            typ = entry[3] if len(entry) > 3 else None
            _issue(nxt, u, cmd, d, typ, damage)

    run(cmds0, 0)
    run(cmds1, 1)

    id_holder = [nxt["next_id"]]
    _tick_busy(nxt, id_holder)
    nxt["next_id"] = id_holder[0]
    dealt_by = _apply_damage(nxt, damage)
    nxt["tick"] = int(state["tick"]) + 1
    _check_done(nxt)

    # reward: damage dealt this tick (p0 perspective) + terminal win/loss
    reward = dealt_by[0] * rw_damage
    if nxt["done"]:
        reward += rw_win if nxt["winner"] == 0 else (0.0 if nxt["winner"] is None else rw_loss)
    nxt["reward"] = reward
    return nxt


# ---------------------------------------------------------------- validation

def _validate_commands(entries, state, owner: int) -> None:
    if not isinstance(entries, list):
        raise ValueError("commands must be a list of [unit_id, cmd, dir?, type?]")
    by_id = {u["id"]: u for u in state["units"]}
    for entry in entries:
        if not isinstance(entry, (list, tuple)) or not (2 <= len(entry) <= 4):
            raise ValueError(f"bad command {entry!r}: [unit_id, cmd, dir?, type?]")
        unit_id, cmd = entry[0], entry[1]
        if not isinstance(unit_id, int) or unit_id not in by_id:
            raise ValueError(f"command for unknown unit {unit_id}")
        if by_id[unit_id]["owner"] != owner:
            raise ValueError(f"unit {unit_id} belongs to player {by_id[unit_id]['owner']}")
        if cmd not in CMD_NAMES:
            raise ValueError(f"bad command code {cmd} (0..6)")
        d = entry[2] if len(entry) > 2 else 0
        if not isinstance(d, int) or d not in DIRS:
            raise ValueError(f"bad direction {d!r} (0=N 1=E 2=S 3=W)")
        typ = entry[3] if len(entry) > 3 else None
        u = by_id[unit_id]
        if cmd == 4 and (u["type"] != "worker" or typ not in WORKER_BUILD):
            raise ValueError(f"build: unit {unit_id} ({u['type']}) cannot build {typ!r}")
        if cmd == 5 and typ not in PRODUCE.get(u["type"], {}):
            raise ValueError(f"produce: unit {unit_id} ({u['type']}) cannot produce {typ!r}")


def validate_state(state: dict) -> None:
    w, h = state.get("grid", [W, H])
    if [w, h] != [W, H]:
        raise ValueError(f"grid must be 16x16, got {w}x{h}")
    terrain = state["terrain"]
    if len(terrain) != H or any(len(r) != W for r in terrain):
        raise ValueError("terrain must be 16 rows x 16 cols")
    for row in terrain:
        for c in row:
            if c not in (0, 1, 2):
                raise ValueError(f"bad terrain cell {c}")
    units = state["units"]
    if not isinstance(units, list) or not units:
        raise ValueError("units must be a non-empty list")
    ids = set()
    for u in units:
        for key in ("id", "owner", "type", "x", "y", "hp", "carry", "cd", "busy"):
            if key not in u:
                raise ValueError(f"unit missing field {key}")
        if u["id"] in ids:
            raise ValueError(f"duplicate unit id {u['id']}")
        ids.add(u["id"])
        if u["owner"] not in (0, 1):
            raise ValueError(f"bad owner {u['owner']}")
        if u["type"] not in UNIT_STATS:
            raise ValueError(f"bad unit type {u['type']}")
        if not (0 <= u["x"] < W and 0 <= u["y"] < H):
            raise ValueError(f"unit {u['id']} out of bounds")
        if terrain[u["y"]][u["x"]] == 1:
            raise ValueError(f"unit {u['id']} sits on a wall")
        if not (1 <= u["hp"] <= UNIT_STATS[u["type"]]["hp"]):
            raise ValueError(f"unit {u['id']} bad hp {u['hp']}")
        if not (0 <= u["carry"] <= CARRY_CAP):
            raise ValueError(f"unit {u['id']} bad carry {u['carry']}")
        if not isinstance(u["cd"], int) or u["cd"] < 0:
            raise ValueError(f"unit {u['id']} bad cd {u['cd']}")
    cells = {(u["x"], u["y"]) for u in units}
    if len(cells) != len(units):
        raise ValueError("two units occupy the same cell")
    bank = state["bank"]
    if len(bank) != 2 or any(not isinstance(g, int) or g < 0 for g in bank):
        raise ValueError("bank must be two non-negative ints")
    damage = state.get("damage", [0, 0])
    if len(damage) != 2 or any(not isinstance(x, int) or x < 0 for x in damage):
        raise ValueError("damage must be two non-negative ints")
    if not isinstance(state["tick"], int) or state["tick"] < 0:
        raise ValueError("tick must be a non-negative int")
    if not isinstance(state["seed"], int):
        raise ValueError("seed must be an int")
    if state.get("winner") not in (None, 0, 1):
        raise ValueError(f"bad winner {state['winner']}")
    if state.get("cause") not in (None, "eliminated", "time"):
        raise ValueError(f"bad cause {state.get('cause')}")
    if state.get("opponent") not in BUILTIN_OPPONENTS + ("external",):
        raise ValueError(f"bad opponent {state.get('opponent')}")


def validate_action(state: dict, action) -> None:
    """Action shape depends on the mode (see module docstring)."""
    if state["opponent"] == "external":
        if not isinstance(action, dict) or "p0" not in action or "p1" not in action:
            raise ValueError("external mode: action must be {'p0': [cmds], 'p1': [cmds]}")
        _validate_commands(action["p0"], state, 0)
        _validate_commands(action["p1"], state, 1)
    else:
        _validate_commands(action, state, 0)


def grid_obs(state: dict) -> np.ndarray:
    """6-channel 16x16 observation: walls, mines, my units, enemy units,
    my buildings, enemy buildings (unit channels intensity = 1.0)."""
    obs = np.zeros((6, H, W), dtype=np.float32)
    for y in range(H):
        for x in range(W):
            c = state["terrain"][y][x]
            if c == 1:
                obs[0, y, x] = 1.0
            elif c == 2:
                obs[1, y, x] = 1.0
    for u in state["units"]:
        mine = 2 if u["owner"] == 0 else 3
        if u["type"] in ("base", "barracks"):
            mine += 2
        obs[mine, u["y"], u["x"]] = 1.0
    return obs
