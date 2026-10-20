"""微RTS（官方种子游戏包，13 G2）。

16×16 MicroRTS 规则移植：采矿 → 建造兵营 → 爆兵 → 摧毁敌方全部单位。
每 tick 为每个单位发一条指令（复合动作）。
模型契约：composite 协议 —— model_inputs 逐单位构造 (1,1546) 输入，
model_decode 做 masked-argmax 并组装指令（协议逻辑从平台 inference.py 原样迁入）。
"""
import numpy as np

from . import env, schemas, strategies

_MR_TYPES = ["base", "barracks", "worker", "light", "heavy", "ranged"]
_MR_ATTACK = {"worker": 1, "light": 2, "heavy": 4, "ranged": 1}
_MR_PRODUCE = {"base": {"worker": 0},
               "barracks": {"light": 1, "heavy": 2, "ranged": 3}}


class MicrortsGame:
    score_bounds = (0, 5000)

    def info(self):
        return {
            "grid": [env.W, env.H],
            "actions": {"0": "wait", "1": "move(dir)", "2": "harvest(dir)",
                        "3": "return(dir)", "4": "build(dir,type)",
                        "5": "produce(dir,type)", "6": "attack(dir)"},
            "action_space": "composite per-unit: [[unit_id, cmd, dir?, type?], ...]",
            "directions": {"0": "N", "1": "E", "2": "S", "3": "W"},
            "two_player": True,
            "opponents": list(env.BUILTIN_OPPONENTS) + ["external"],
            "default_rewards": dict(env.DEFAULT_REWARDS),
            "max_batch": 128,
            "obs_modes": ["grid"],
            "obs_shape": [6, env.H, env.W],
            "time_limit": env.TIME_LIMIT,
            "deterministic": "map and all dynamics deterministic given seed",
            "schemas": schemas.ENV_SCHEMAS,
        }

    def _render(self, state, prev=None):
        """通用棋盘渲染：terrain → cell-id 网格（empty/wall/mine）；
        单位补 hp_max（渲染 v2 血条用）并追加事件。"""
        _CELL = {0: "empty", 1: "wall", 2: "mine"}
        b = [[_CELL.get(c, "empty") for c in row] for row in state["terrain"]]
        units = [{**u, "hp_max": env.UNIT_STATS[u["type"]]["hp"]}
                 for u in state["units"]]
        events = []
        if prev is not None:
            dmg = sum(state.get("damage") or [0, 0])
            prev_dmg = sum(prev.get("damage") or [0, 0])
            if dmg > prev_dmg:
                events.append("attack")
            if len(state["units"]) < len(prev["units"]):
                events.append("death")
        return {**state, "board": b, "units": units, "events": events}

    def new_state(self, seed, options=None):
        return self._render(env.new_state(int(seed), options))

    def step_state(self, state, action, rewards=None):
        return self._render(env.step_state(state, action, rewards), prev=state)

    def validate_state(self, state):
        env.validate_state(state)

    def validate_action(self, action, state=None):
        if state is None:
            raise ValueError("microrts action validation requires the state")
        env.validate_action(state, action)

    def obs(self, state, mode=None):
        if mode is None or mode == "grid":
            return env.grid_obs(state).tolist()
        return None

    # ------------------------------------------------------------------- ai
    def ai_action(self, payload):
        state = payload["state"]
        env.validate_state(state)
        strategy = payload.get("strategy") or "worker_rush"
        if strategy not in strategies.BUILTIN:
            raise ValueError(f"unknown strategy {strategy!r} "
                             f"(choose from {list(strategies.BUILTIN)})")
        owner = payload.get("owner", 0)
        cmds = strategies.builtin_commands(strategy, state, owner=owner)
        return {"action": cmds, "strategy": strategy, "owner": owner}

    def opponent_action(self, state, config):
        ctype = config.get("type", "ai")
        if ctype != "ai":
            raise ValueError(f"unsupported opponent type {ctype!r} (builtin: ai)")
        strategy = config.get("strategy", "light_rush")
        if strategy not in strategies.BUILTIN:
            raise ValueError(f"unknown strategy {strategy!r}")
        return strategies.builtin_commands(strategy, state, owner=1)

    def sample_action(self, state):
        return strategies.builtin_commands("worker_rush", state, owner=0)

    # ------------------------------------------------ composite model protocol
    def _mr_grid(self, state, owner):
        grid = env.grid_obs(state)  # p0 perspective
        if owner == 1:
            grid[[2, 3]] = grid[[3, 2]]
            grid[[4, 5]] = grid[[5, 4]]
        return grid

    def _unit_feats(self, state, unit):
        f = np.zeros(10, dtype=np.float32)
        f[_MR_TYPES.index(unit["type"])] = 1.0
        f[6] = unit["x"] / 15.0
        f[7] = unit["y"] / 15.0
        f[8] = unit["hp"] / float(env.UNIT_STATS[unit["type"]]["hp"])
        f[9] = (unit.get("cd") or 0) / 5.0
        return f

    def _unit_input(self, state, owner, unit):
        grid = self._mr_grid(state, owner).reshape(-1)
        feats = self._unit_feats(state, unit)
        return np.concatenate([grid, feats]).reshape(1, -1).astype(np.float32)

    def _mask_for(self, unit_type):
        mask = np.full(140, -np.inf, dtype=np.float32)
        allowed = []

        def add(cmd, types):
            for t in types:
                for d in range(4):
                    allowed.append((cmd, d, t))

        add(0, (0,))
        add(1, (0,))
        if unit_type == "worker":
            add(2, (0,))
            add(3, (0,))
            add(4, (4,))
        if unit_type in _MR_PRODUCE:
            add(5, tuple(_MR_PRODUCE[unit_type].values()))
        if _MR_ATTACK.get(unit_type, 0) > 0:
            add(6, (0,))
        for cmd, d, t in allowed:
            mask[cmd * 20 + d * 4 + t] = 0.0
        return mask

    def model_inputs(self, state, owner=0):
        """composite 协议：每个空闲己方单位一组 (1,1546) 输入。"""
        return [self._unit_input(state, owner, u).tolist()
                for u in sorted(state["units"], key=lambda u: u["id"])
                if u["owner"] == owner and u["busy"] is None]

    def model_decode(self, outputs, state, owner=0):
        """composite 协议：逐组 logits 做 masked-argmax 并组装指令。"""
        cmds = []
        it = iter(outputs)
        for u in sorted(state["units"], key=lambda u: u["id"]):
            if u["owner"] != owner or u["busy"] is not None:
                continue
            logits = np.asarray(next(it), dtype=np.float32) \
                + self._mask_for(u["type"])
            idx = int(np.argmax(logits))
            cmd, d, typ = idx // 20, (idx // 4) % 5, idx % 4
            if cmd == 4:
                cmds.append([u["id"], cmd, d, "barracks"])
            elif cmd == 5:
                tmap = {0: "worker", 1: "light", 2: "heavy", 3: "ranged"}
                cmds.append([u["id"], cmd, d, tmap.get(typ, "worker")])
            elif cmd in (0, 1, 2, 3, 6):
                cmds.append([u["id"], cmd, d])
        return cmds


def get_adapter():
    return MicrortsGame()
