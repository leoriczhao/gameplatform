"""How the platform calls a game adapter.

These are the call semantics every host must share: the reward-argument
fallback, the ai_action → opponent_action fallback, the owner-argument
fallback of the composite model protocol, batch validation, and the JSON
boundary values cross between the sandbox worker and the server.
"""
from __future__ import annotations

import json

import numpy as np

MAX_BATCH = 256


def wire(value):
    """The worker's JSON boundary: tuples become lists, unknown objects strings."""
    return json.loads(json.dumps(value, default=str, ensure_ascii=False))


class GameCalls:
    """One adapter behind the platform's call semantics.

    ``wire_outputs=True`` applies the worker's JSON boundary to every return
    value, so an in-process host sees exactly what a sandboxed one would.
    """

    def __init__(self, adapter, *, wire_outputs: bool = False):
        self.adapter = adapter
        self._out = wire if wire_outputs else (lambda value: value)

    # ------------------------------------------------------------ engine
    def info(self) -> dict:
        info = self.adapter.info() if hasattr(self.adapter, "info") else {}
        return self._out(info)

    def score_bounds(self) -> list[int]:
        lo, hi = getattr(self.adapter, "score_bounds", (0, 1_000_000))
        return [int(lo), int(hi)]

    def new_state(self, seed, options=None):
        return self._out(self.adapter.new_state(seed, options))

    def step_state(self, state, action, rewards=None):
        if rewards is None:
            return self._out(self.adapter.step_state(state, action))
        try:
            return self._out(self.adapter.step_state(state, action, rewards))
        except TypeError:
            return self._out(self.adapter.step_state(state, action))

    def validate_state(self, state) -> bool:
        self.adapter.validate_state(state)
        return True

    def validate_action(self, action, state=None) -> bool:
        self.adapter.validate_action(action, state)
        return True

    def obs(self, state, mode=None):
        if not hasattr(self.adapter, "obs"):
            return None
        return self._out(self.adapter.obs(state, mode))

    def obs_array(self, state, mode=None) -> np.ndarray | None:
        """obs() as float32, the way the server packs OpenEnv tensors. A plain
        (nested) number list survives the JSON boundary unchanged, so only
        other return types take the JSON path the worker would apply."""
        if not hasattr(self.adapter, "obs"):
            return None
        obs = self.adapter.obs(state, mode)
        if obs is None:
            return None
        if not isinstance(obs, (list, tuple)):
            obs = wire(obs)
        return np.asarray(obs, dtype=np.float32)

    def opponent_action(self, state, config):
        return self._out(self.adapter.opponent_action(state, config))

    def sample_action(self, state):
        return self._out(self.adapter.sample_action(state))

    def ai_action(self, payload: dict):
        if hasattr(self.adapter, "ai_action"):
            return self._out(self.adapter.ai_action(payload))
        # 未实现 ai_action 时回退到 opponent_action（ai_strategies 型游戏）
        if hasattr(self.adapter, "opponent_action"):
            cfg = {"type": "ai"}
            if payload.get("strategy"):
                cfg["strategy"] = payload["strategy"]
            return self._out({"action": self.adapter.opponent_action(payload["state"], cfg)})
        raise ValueError("该游戏未提供内置 AI")

    def model_inputs(self, state, owner=0):
        if not hasattr(self.adapter, "model_inputs"):
            raise ValueError("该游戏未声明 composite 模型协议（model_inputs）")
        try:
            return self._out(self.adapter.model_inputs(state, owner))
        except TypeError:
            return self._out(self.adapter.model_inputs(state))

    def model_decode(self, outputs, state, owner=0):
        if not hasattr(self.adapter, "model_decode"):
            raise ValueError("该游戏未声明 composite 模型协议（model_decode）")
        try:
            return self._out(self.adapter.model_decode(outputs, state, owner))
        except TypeError:
            return self._out(self.adapter.model_decode(outputs, state))

    # ------------------------------------------------------------ batches
    def new_batch(self, seeds, options=None, obs_mode=None) -> list[dict]:
        results = []
        for seed in seeds:
            state = self.adapter.new_state(seed, options)
            item = {"state": state}
            if obs_mode is not None:
                item["obs"] = self.adapter.obs(state, obs_mode)
            results.append(item)
        return self._out(results)

    def step_batch(self, states, actions, rewards=None, obs_mode=None) -> list[dict]:
        if len(states) != len(actions) or not 1 <= len(states) <= MAX_BATCH:
            raise ValueError(f"batch requires 1..{MAX_BATCH} states and matching actions")
        for state, action in zip(states, actions):
            self.adapter.validate_state(state)
            self.adapter.validate_action(action, state)
        results = []
        for state, action in zip(states, actions):
            nxt = GameCalls(self.adapter).step_state(state, action, rewards)
            item = {"state": nxt, "reward": nxt.get("reward", 0.0),
                    "done": nxt.get("done", False)}
            if "ate" in nxt:
                item["ate"] = nxt["ate"]
            if obs_mode is not None:
                item["obs"] = self.adapter.obs(nxt, obs_mode)
            results.append(item)
        return self._out(results)

    # ------------------------------------------------------------ IPC
    def dispatch(self, op: str, args: dict):
        """Run one named operation with keyword args (the worker's protocol)."""
        if op == "new_batch":
            return self.new_batch(args["seeds"], args.get("options"), args.get("obs_mode"))
        if op == "step_batch":
            return self.step_batch(args["states"], args["actions"],
                                   args.get("rewards"), args.get("obs_mode"))
        if op == "info":
            return self.info()
        if op == "score_bounds":
            return self.score_bounds()
        if op == "new_state":
            return self.new_state(args["seed"], args.get("options"))
        if op == "step_state":
            return self.step_state(args["state"], args["action"], args.get("rewards"))
        if op == "validate_state":
            return self.validate_state(args["state"])
        if op == "validate_action":
            return self.validate_action(args["action"], args["state"])
        if op == "opponent_action":
            return self.opponent_action(args["state"], args["config"])
        if op == "sample_action":
            return self.sample_action(args["state"])
        if op == "obs":
            return self.obs(args["state"], args.get("mode"))
        if op == "model_inputs":
            return self.model_inputs(args["state"], args.get("owner", 0))
        if op == "model_decode":
            return self.model_decode(args["outputs"], args["state"], args.get("owner", 0))
        if op == "ai_action":
            return self.ai_action(args["payload"])
        raise ValueError(f"unknown op {op!r}")
