"""推箱子（GDK-UG 范例 2）：PvE + units 渲染约定。
动作：方向 0=上 1=右 2=下 3=左（与平台 DIRS 约定一致）。
state 顶层：board（地形）+ units（[{id,x,y,type}]，worker/box）。
"""

W, H = 6, 4
LEVEL = [
    "######",
    "#@$.##",   # 箱子在 (2,1)，目标 (4,1)：右推两次完成
    "#....#",
    "######",
]
DIRS = {0: (0, -1), 1: (1, 0), 2: (0, 1), 3: (-1, 0)}


def _terrain(x, y):
    if y < 0 or y >= H or x < 0 or x >= W or LEVEL[y][x] == "#":
        return "wall"
    return "target" if LEVEL[y][x] == "." else "empty"


class Sokoban:
    score_bounds = (0, 1000)

    def info(self):
        return {"grid": [W, H], "action_space": "dir 0-3"}

    def new_state(self, seed, options=None):
        units = []
        board = []
        for y in range(H):
            row = []
            for x in range(W):
                c = LEVEL[y][x]
                if c == "@":
                    units.append({"id": 1, "x": x, "y": y, "type": "worker"})
                elif c == "$":
                    units.append({"id": 2, "x": x, "y": y, "type": "box"})
                row.append(_terrain(x, y))
            board.append(row)
        return {"tick": 0, "done": False, "winner": None, "cause": None,
                "steps": 0, "reward": 0.0, "board": board, "units": units}

    def validate_state(self, state):
        if len(state["board"]) != H or any(len(r) != W for r in state["board"]):
            raise ValueError(f"board 必须是 {W}x{H}")
        for u in state.get("units", []):
            if u["type"] not in ("worker", "box"):
                raise ValueError(f"未知单位类型 {u['type']}")

    def validate_action(self, action, state):
        if not isinstance(action, int) or action not in DIRS:
            raise ValueError("动作需为 0-3 的方向")

    def step_state(self, state, action):
        if state.get("done"):
            return state
        units = [{**u} for u in state["units"]]
        worker = next(u for u in units if u["type"] == "worker")
        dx, dy = DIRS[action]
        nx, ny = worker["x"] + dx, worker["y"] + dy
        if _terrain(nx, ny) == "wall":
            return {**state, "units": units, "tick": state["tick"] + 1,
                    "steps": state["steps"] + 1}   # 撞墙：白走一步
        box = next((u for u in units if u["x"] == nx and u["y"] == ny), None)
        if box:
            bx, by = nx + dx, ny + dy
            if _terrain(bx, by) == "wall" or any(
                    u["x"] == bx and u["y"] == by for u in units):
                return {**state, "units": units, "tick": state["tick"] + 1,
                        "steps": state["steps"] + 1}   # 推不动
            box["x"], box["y"] = bx, by
        worker["x"], worker["y"] = nx, ny
        done = _terrain(box["x"], box["y"]) == "target" if box else False
        s = {**state, "units": units, "tick": state["tick"] + 1,
             "steps": state["steps"] + 1}
        if done:
            s["done"] = True; s["winner"] = 0; s["cause"] = "solved"
            s["reward"] = max(0.0, 1000.0 - 20.0 * s["steps"])
        return s

    def sample_action(self, state):
        return state["tick"] % 4


def get_adapter():
    return Sokoban()
