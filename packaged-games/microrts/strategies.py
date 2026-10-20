"""Built-in deterministic strategies for microrts (MicroRTS classics).

Each strategy is a pure function of the state returning the command list for
the given owner. Deterministic: every choice is tie-broken by (distance, unit
id, direction order). Ported in spirit from the standard MicroRTS scripted
bots used in the CoG competitions:

  worker_rush  spams workers forever; harvests, then swarms the enemy
  light_rush   classic build order: 2 workers -> barracks -> light rush
  ranged_rush  like light_rush but with ranged units that keep distance
"""
from __future__ import annotations

from collections import deque

from . import env


def _units(state, owner):
    return [u for u in state["units"] if u["owner"] == owner]


def _by_type(state, owner, typ):
    return [u for u in state["units"] if u["owner"] == owner and u["type"] == typ]


def _nearest(state, x, y, candidates):
    """Closest candidate by (manhattan, id); None if empty."""
    if not candidates:
        return None
    return min(candidates,
               key=lambda u: (abs(u["x"] - x) + abs(u["y"] - y), u["id"]))


def _nearest_enemy(state, x, y, owner):
    return _nearest(state, x, y,
                    [u for u in state["units"] if u["owner"] != owner])


def _nearest_mine(state, x, y):
    mines = [(mx, my)
             for my in range(env.H) for mx in range(env.W)
             if state["terrain"][my][mx] == 2]
    if not mines:
        return None
    return min(mines, key=lambda m: (abs(m[0] - x) + abs(m[1] - y), m[1], m[0]))


def _nearest_base(state, owner, x, y):
    bases = _by_type(state, owner, "base")
    return _nearest(state, x, y, bases)


def _path_dir(state, x, y, tx, ty):
    """BFS over terrain (walls AND units block, except the target cell itself
    — e.g. the base stands on its own cell); first step direction."""
    if (x, y) == (tx, ty):
        return 0
    occupied = {(u["x"], u["y"]) for u in state["units"]} - {(x, y), (tx, ty)}
    prev = {(x, y): None}
    frontier = deque([(x, y)])
    while frontier:
        cx, cy = frontier.popleft()
        for d, (dx, dy) in sorted(env.DIRS.items()):  # deterministic order N E S W
            nx, ny = cx + dx, cy + dy
            if not (0 <= nx < env.W and 0 <= ny < env.H):
                continue
            if state["terrain"][ny][nx] == 1 or (nx, ny) in occupied \
                    or (nx, ny) in prev:
                continue
            prev[(nx, ny)] = (cx, cy)
            if (nx, ny) == (tx, ty):
                # walk back to the first step
                cur = (nx, ny)
                while prev[cur] != (x, y):
                    cur = prev[cur]
                for d2, (dx2, dy2) in env.DIRS.items():
                    if (x + dx2, y + dy2) == cur:
                        return d2
            frontier.append((nx, ny))
    return 0  # unreachable (shouldn't happen on open maps)


def _dir_toward(state, u, tx, ty):
    """Direction that moves u one step closer to (tx, ty), 0 if adjacent."""
    if (u["x"], u["y"]) == (tx, ty) or (abs(u["x"] - tx) + abs(u["y"] - ty)) == 1:
        return 0
    return _path_dir(state, u["x"], u["y"], tx, ty)


def _dir_to(x, y, tx, ty):
    """Exact direction from (x, y) to an adjacent cell (tx, ty)."""
    for d, (dx, dy) in sorted(env.DIRS.items()):
        if x + dx == tx and y + dy == ty:
            return d
    return 0


def _attack_dir(u, e):
    """Direction toward the enemy: exact axis if aligned, else the dominant
    axis (ranged shots only hit when aligned, like the original)."""
    if abs(u["x"] - e["x"]) >= abs(u["y"] - e["y"]):
        return 1 if e["x"] > u["x"] else 3
    return 2 if e["y"] > u["y"] else 0


def _free_dir(state, u):
    """First free adjacent cell direction (N E S W)."""
    for d, (dx, dy) in sorted(env.DIRS.items()):
        if env._free(state, u["x"] + dx, u["y"] + dy):
            return d
    return 0


# ---------------------------------------------------------------- worker rush

def worker_rush(state, owner: int):
    cmds = []
    enemies_near = False
    for u in _units(state, owner):
        e = _nearest_enemy(state, u["x"], u["y"], owner)
        if e is not None and abs(u["x"] - e["x"]) + abs(u["y"] - e["y"]) <= 6:
            enemies_near = True
            break

    for u in sorted(_units(state, owner), key=lambda u: u["id"]):
        if u["busy"] is not None:
            continue
        if u["type"] == "base":
            # spam workers while affordable and below the swarm cap
            workers = len(_by_type(state, owner, "worker"))
            if state["bank"][owner] >= 1 and workers < 30:
                cmds.append([u["id"], 5, _free_dir(state, u), "worker"])
            continue
        if u["type"] == "worker":
            if enemies_near:
                e = _nearest_enemy(state, u["x"], u["y"], owner)
                if e is not None:
                    if abs(u["x"] - e["x"]) + abs(u["y"] - e["y"]) == 1:
                        cmds.append([u["id"], 6, _dir_to(u["x"], u["y"], e["x"], e["y"])])
                    else:
                        cmds.append([u["id"], 1, _dir_toward(state, u, e["x"], e["y"])])
                continue
            if u["carry"] > 0:
                b = _nearest_base(state, owner, u["x"], u["y"])
                if b is None:
                    continue
                if env._adjacent(state, u["x"], u["y"], owner, "base"):
                    cmds.append([u["id"], 3, 0])
                else:
                    cmds.append([u["id"], 1, _dir_toward(state, u, b["x"], b["y"])])
                continue
            m = _nearest_mine(state, u["x"], u["y"])
            if m is None:
                continue
            if abs(u["x"] - m[0]) + abs(u["y"] - m[1]) == 1:
                cmds.append([u["id"], 2, _dir_to(u["x"], u["y"], m[0], m[1])])
            else:
                cmds.append([u["id"], 1, _dir_toward(state, u, m[0], m[1])])
    return cmds


# ---------------------------------------------------------------- light rush

def light_rush(state, owner: int):
    return _barracks_rush(state, owner, "light")


def ranged_rush(state, owner: int):
    return _barracks_rush(state, owner, "ranged")


def _barracks_rush(state, owner: int, combat_type: str):
    """Classic build order: 2 workers -> barracks -> spam the combat unit.
    ranged units kite (keep 2-3 cells of distance); melee close in."""
    cmds = []
    workers = _by_type(state, owner, "worker")
    barracks = _by_type(state, owner, "barracks")
    combat = [u for u in _units(state, owner)
              if u["type"] in ("light", "heavy", "ranged")]

    for u in sorted(_units(state, owner), key=lambda u: u["id"]):
        if u["busy"] is not None:
            continue
        if u["type"] == "base":
            if len(workers) < 2 and state["bank"][owner] >= 1:
                cmds.append([u["id"], 5, _free_dir(state, u), "worker"])
            continue
        if u["type"] == "barracks":
            if state["bank"][owner] >= env.PRODUCE["barracks"][combat_type][0] \
                    and len(combat) < 25:
                cmds.append([u["id"], 5, _free_dir(state, u), combat_type])
            continue
        if u["type"] == "worker":
            if not barracks and state["bank"][owner] >= env.WORKER_BUILD["barracks"][0]:
                if len([w for w in workers if w["busy"] is not None
                        and w["busy"]["cmd"] == 4]) == 0:
                    cmds.append([u["id"], 4, _free_dir(state, u), "barracks"])
                    continue
            if u["carry"] > 0:
                b = _nearest_base(state, owner, u["x"], u["y"])
                if b is None:
                    continue
                if env._adjacent(state, u["x"], u["y"], owner, "base"):
                    cmds.append([u["id"], 3, 0])
                else:
                    cmds.append([u["id"], 1, _dir_toward(state, u, b["x"], b["y"])])
                continue
            m = _nearest_mine(state, u["x"], u["y"])
            if m is None:
                continue
            if abs(u["x"] - m[0]) + abs(u["y"] - m[1]) == 1:
                cmds.append([u["id"], 2, _dir_to(u["x"], u["y"], m[0], m[1])])
            else:
                cmds.append([u["id"], 1, _dir_toward(state, u, m[0], m[1])])
            continue
        if u["type"] in ("light", "heavy", "ranged"):
            e = _nearest_enemy(state, u["x"], u["y"], owner)
            if e is None:
                continue
            dist = abs(u["x"] - e["x"]) + abs(u["y"] - e["y"])
            d = _dir_toward(state, u, e["x"], e["y"])
            if u["type"] == "ranged" and dist <= 2:
                # kite: back off along the opposite of the enemy direction
                away = {0: 2, 1: 3, 2: 0, 3: 1}[d]
                cmds.append([u["id"], 1, away])
            elif dist == 1:
                cmds.append([u["id"], 6, _dir_to(u["x"], u["y"], e["x"], e["y"])])
            elif u["type"] == "ranged" and dist <= 3:
                cmds.append([u["id"], 6, _attack_dir(u, e)])
            else:
                cmds.append([u["id"], 1, d])
    return cmds


BUILTIN = {"worker_rush": worker_rush, "light_rush": light_rush,
           "ranged_rush": ranged_rush}


def builtin_commands(strategy: str, state, owner: int = 1):
    """Command list for `owner` produced by the named deterministic strategy."""
    return BUILTIN[strategy](state, owner)
