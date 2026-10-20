"""猜数字（GDK-UG 范例 1）：PvE + 内置 AI(binary) + 榜单。
state.board 是 10×10 猜测记录板——演示通用渲染器的 palette 约定。
动作：0-99 的整数（猜哪个数）。
"""
import random

W, H = 10, 10
MAX_GUESSES = 20


def _mark(state, guess):
    y, x = divmod(guess, 10)
    state["board"][y][x] = ("hit" if guess == state["secret"]
                            else "low" if guess < state["secret"] else "high")


def _copy(state):
    return {**state, "board": [row[:] for row in state["board"]]}


class GuessNumber:
    score_bounds = (0, 100)

    def info(self):
        return {"grid": [W, H], "action_space": "guess 0-99",
                "max_guesses": MAX_GUESSES}

    def new_state(self, seed, options=None):
        rng = random.Random(seed)
        return {
            "tick": 0, "done": False, "winner": None, "cause": None,
            "secret": rng.randrange(100), "misses": 0, "reward": 0.0,
            "board": [["empty"] * W for _ in range(H)],
        }

    def validate_state(self, state):
        if not isinstance(state, dict) or "board" not in state:
            raise ValueError("state 必须含 board")
        if len(state["board"]) != H or any(len(r) != W for r in state["board"]):
            raise ValueError(f"board 必须是 {W}x{H}")

    def validate_action(self, action, state):
        if not isinstance(action, int) or not 0 <= action <= 99:
            raise ValueError("动作需为 0-99 的整数")

    def step_state(self, state, action):
        if state.get("done"):
            return state
        s = _copy(state)
        s["tick"] += 1
        _mark(s, action)
        if action == s["secret"]:
            s["done"] = True; s["winner"] = 0; s["cause"] = "hit"
        else:
            s["misses"] += 1
            if s["misses"] >= MAX_GUESSES:
                s["done"] = True; s["winner"] = None
                s["cause"] = "out_of_guesses"
        if s["done"]:
            s["reward"] = 100.0 - 5.0 * s["misses"] if s["winner"] == 0 else 0.0
        return s

    def opponent_action(self, state, config):
        """binary 策略：按历史反馈折半搜索（确定性）。"""
        lo, hi = 0, 99
        for y in range(H):
            for x in range(W):
                cell = state["board"][y][x]
                g = y * 10 + x
                if cell == "low" and g > lo:
                    lo = g + 1
                elif cell == "high" and g < hi:
                    hi = g - 1
        return (lo + hi) // 2

    def sample_action(self, state):
        return random.Random(state["tick"] * 7919).randrange(100)


def get_adapter():
    return GuessNumber()
