"""贪吃蛇（官方种子游戏包，13 G2）。

20×20 网格贪吃蛇。相对动作空间（0=左转 1=直行 2=右转）。
- env.py：规则内核（纯函数，与 snake.cree1p.com 服务位级一致）
- ai.py：内置 DQN（rotwin R=10，1334 维观测），权重随包（weights.npz）
- 模型契约：simple 协议，obs_mode=rotwin，in (1,1334) → out (1,3)
"""
from . import ai, env, schemas


class SnakeGame:
    score_bounds = (0, 1000)

    def __init__(self):
        self.model = ai.SnakeAI()

    def info(self):
        return {
            "grid": [env.GRID_W, env.GRID_H],
            "actions": {"0": "left", "1": "straight", "2": "right"},
            "action_space": "discrete(3)",
            "default_rewards": dict(env.DEFAULT_REWARDS),
            "max_batch": 256,
            "obs_modes": ["grid", "rotwin"],
            "obs_shape": [3, env.GRID_H + 2, env.GRID_W + 2],
            "deterministic": "food spawn is deterministic given (seed, tick)",
            "schemas": schemas.ENV_SCHEMAS,
        }

    def _render(self, state):
        """通用棋盘渲染（12 §5）：body/food → 20×20 cell-id 网格；
        渲染 v2（16）：事件供前端动效/音效使用。"""
        b = [["empty"] * env.GRID_W for _ in range(env.GRID_H)]
        for i, (x, y) in enumerate(state["body"]):
            b[y][x] = "head" if i == 0 else "body"
        if state["food"]:
            fx, fy = state["food"]
            b[fy][fx] = "food"
        events = []
        if state.get("ate"):
            events.append("eat")
        if state.get("done"):
            events.append("death")
        return {**state, "board": b, "events": events}

    def new_state(self, seed, options=None):
        return self._render(env.new_state(int(seed)))

    def step_state(self, state, action, rewards=None):
        return self._render(env.step_state(state, action, rewards))

    def validate_state(self, state):
        env.validate_state(state)

    def validate_action(self, action, state=None):
        if action not in (0, 1, 2):
            raise ValueError(f"action must be 0/1/2 (relative), got {action}")

    def obs(self, state, mode=None):
        if mode == "rotwin":
            return ai.rotwin_obs(state["body"], state["direction"],
                                 state["food"]).tolist()
        if mode is None or mode == "grid":
            return env.grid_obs(state["body"], state["food"]).tolist()
        return None

    def ai_action(self, payload):
        state = payload.get("state") or {}
        body = state.get("body") or []
        if len(body) < 2:
            raise ValueError("body must have at least 2 cells")
        if len(body) > env.GRID_W * env.GRID_H:
            raise ValueError("body longer than the board")
        for x, y in body:
            if not (0 <= x < env.GRID_W and 0 <= y < env.GRID_H):
                raise ValueError(f"cell ({x},{y}) outside the board")
        if len({tuple(p) for p in body}) != len(body):
            raise ValueError("body contains duplicate cells")
        food = state.get("food")
        if food is not None:
            fx, fy = food
            if not (0 <= fx < env.GRID_W and 0 <= fy < env.GRID_H):
                raise ValueError("food outside the board")
            if tuple(food) in map(tuple, body):
                raise ValueError("food overlaps the snake")
        action, q = self.model.action(body, state["direction"], food)
        return {"action": action, "action_name": ai.ACTION_NAMES[action],
                "q": q}

    def sample_action(self, state):
        return self.model.action(state["body"], state["direction"],
                                 state.get("food"))[0]


def get_adapter():
    return SnakeGame()
