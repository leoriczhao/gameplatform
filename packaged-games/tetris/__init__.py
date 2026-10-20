"""俄罗斯方块（官方种子游戏包，13 G2）。

10×20 棋盘，7-bag 出块（seed 可复现）。动作：0=左移 1=右移 2=旋转 3=硬降；
消行得分 1/4/9/16（1/2/3/4 行）。内置启发式 AI 演示。
模型契约：simple 协议，obs=grid，in (1,2,20,10) → out (1,4)。
"""
from . import baseline, env, schemas


class TetrisGame:
    score_bounds = (0, 1_000_000)

    def info(self):
        return {
            "grid": [env.W, env.H],
            "actions": {"0": "left", "1": "right", "2": "rotate", "3": "hard_drop"},
            "action_space": "discrete(4)",
            "default_rewards": dict(env.DEFAULT_REWARDS),
            "max_batch": 256,
            "obs_modes": ["grid"],
            "obs_shape": [2, env.H, env.W],
            "deterministic": "7-bag piece sequence is deterministic given (seed, bag_idx)",
            "notes": ("reward 只在硬降时产生：step + k^2*line + (lockout 时 death)；"
                      "自由动作（左/右/旋转）不推进 tick 且 reward 为 0"),
            "schemas": schemas.ENV_SCHEMAS,
        }

    def _next_board(self, state):
        """渲染 v2：NEXT 小棋盘（4×4，归一化到左上角）。"""
        nid = state.get("next")
        if nid not in env.ROTATIONS:
            return None
        cells = env.cells_of({"id": nid, "rot": 0, "x": 0, "y": 0})
        min_x = min(c[0] for c in cells)
        min_y = min(c[1] for c in cells)
        grid = [["0"] * 4 for _ in range(4)]
        for cx, cy in cells:
            gx, gy = cx - min_x, cy - min_y
            if 0 <= gx < 4 and 0 <= gy < 4:
                grid[gy][gx] = str(nid)
        return grid

    def _render(self, state, prev=None):
        """通用棋盘渲染：state.board（整数 0..7）另存字符串网格到 render_board，
        当前方块覆盖为 active（引擎仍用整数 board）；渲染 v2 追加 next_board 与事件。"""
        b = [[str(cell) for cell in row] for row in state["board"]]
        for cx, cy in env.cells_of(state["piece"]):
            if 0 <= cx < env.W and 0 <= cy < env.H:
                b[cy][cx] = "active"
        events = []
        if prev is not None and state.get("lines", 0) > prev.get("lines", 0):
            events.append("clear")
        return {**state, "render_board": b,
                "next_board": self._next_board(state), "events": events}

    def new_state(self, seed, options=None):
        return self._render(env.new_state(int(seed)))

    def step_state(self, state, action, rewards=None):
        return self._render(env.step_state(state, action, rewards), prev=state)

    def validate_state(self, state):
        env.validate_state(state)

    def validate_action(self, action, state=None):
        if action not in (0, 1, 2, 3):
            raise ValueError(f"action must be 0..3, got {action}")

    def obs(self, state, mode=None):
        if mode is None or mode == "grid":
            return env.grid_obs(state).tolist()
        return None

    def ai_action(self, payload):
        state = payload.get("state") or {}
        env.validate_state(state)
        action = baseline.baseline_action(state)
        return {"action": action, "action_name": env.ACTION_NAMES[action]}

    def sample_action(self, state):
        return baseline.baseline_action(state)


def get_adapter():
    return TetrisGame()
