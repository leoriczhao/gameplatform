"""石头剪刀布（GDK-UG 范例 3）：choice 型 PvP + PvE。
动作：0=石头 1=剪刀 2=布。
PvP：step_state 接收 {"p0": a, "p1": b} 复合动作（双方已提交才推进，平台协议）；
PvE：step_state 接收整数（平台侧 p0），对手由内置随机策略代打。
board 是 1×3 记分条：[蓝方得分, 上局结果, 红方得分]。
"""
import random

BEATS = {0: 1, 1: 2, 2: 0}   # key 胜 value
TARGET = 3                    # 先胜 3 局


def _round(s, a, b):
    s["tick"] += 1
    if a == b:
        return "draw"
    if BEATS[a] == b:
        s["s0"] += 1
        return "p0"
    s["s1"] += 1
    return "p1"


def _finish(s):
    if s["s0"] >= TARGET:
        s["done"], s["winner"], s["cause"] = True, 0, "win3"
    elif s["s1"] >= TARGET:
        s["done"], s["winner"], s["cause"] = True, 1, "win3"
    elif s["tick"] >= 9:   # 平局封顶
        s["done"], s["winner"], s["cause"] = True, None, "draw"
    if s["done"]:
        s["reward"] = 20.0 * s["s0"] if s["winner"] == 0 else 0.0


class RockPaperScissors:
    score_bounds = (0, 100)

    def info(self):
        return {"grid": [3, 1], "action_space": "0=石头 1=剪刀 2=布",
                "choices": ["石头", "剪刀", "布"]}

    def new_state(self, seed, options=None):
        return {"tick": 0, "done": False, "winner": None, "cause": None,
                "s0": 0, "s1": 0, "reward": 0.0, "last": None,
                "board": [["0", "empty", "0"]]}

    def _render(self, s, last):
        return [[str(min(s["s0"], 3)), last or "empty", str(min(s["s1"], 3))]]

    def validate_state(self, state):
        if len(state["board"]) != 1 or len(state["board"][0]) != 3:
            raise ValueError("board 必须是 1x3")

    def validate_action(self, action, state):
        if isinstance(action, dict):
            for k, v in action.items():
                if k not in ("p0", "p1"):
                    raise ValueError("PvP 动作键需为 p0/p1")
                if v is None:          # 未提交方占位（平台单侧校验）
                    continue
                if not isinstance(v, int) or v not in (0, 1, 2):
                    raise ValueError("PvP 动作需为 {p0:0-2, p1:0-2}")
            return
        if not isinstance(action, int) or action not in (0, 1, 2):
            raise ValueError("动作需为 0-2")

    def step_state(self, state, action):
        if state.get("done"):
            return state
        s = {**state}
        if isinstance(action, dict):      # PvP：双方已提交
            a, b = action["p0"], action["p1"]
            last = _round(s, a, b)
            _finish(s)
            s["board"] = self._render(s, last)
            s["last"] = {"p0": a, "p1": b}
            return s
        a = action                        # PvE：对手由内置随机代打
        b = random.Random(s["tick"] * 31 + 7).randrange(3)
        last = _round(s, a, b)
        if s["s1"] >= TARGET or (s["tick"] >= 9 and s["s0"] < TARGET):
            _finish(s)
        else:
            _finish(s)   # pve：五局后按 s0/s1 判定
        s["board"] = self._render(s, last)
        s["last"] = {"p0": a, "p1": b}
        return s

    def sample_action(self, state):
        return state["tick"] % 3


def get_adapter():
    return RockPaperScissors()
