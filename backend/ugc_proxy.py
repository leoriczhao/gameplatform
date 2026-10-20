"""ProxyAdapter (11 P2): a sandboxed UGC game wearing the EnvAdapter face.

Once registered into `registry`, every existing platform surface (env API,
play sessions, scores, AI endpoint, ratings, watch/replay) works unchanged.
AI 咨询端点需要一个 pydantic 模型；这里提供一个通用模型并把调用转发给
沙箱内的 ai_action。
"""
from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

import ugc_runner


class UGCAIRequest(BaseModel):
    """通用 AI 咨询请求（/api/{slug}/ai/action）"""
    state: dict = Field(description="当前 state")
    strategy: str | None = Field(default=None, description="策略名（缺省用游戏默认）")
    owner: int = Field(default=0, description="阵营 0|1")


class ProxyAdapter:
    """Implements the EnvAdapter surface used by the platform routers."""

    def __init__(self, game_id: str, game_dir: str | Path, meta: dict,
                 on_unhealthy=None, author: str | None = None):
        self.game_id = game_id
        self.name = meta["title"]
        self.description = meta["description"]
        self.author = author
        self.game_dir = Path(game_dir)
        self.meta = meta
        pvp_meta = meta.get("pvp") or {}
        self.pvp_enabled = bool(pvp_meta.get("enabled"))
        # unit 型有空指令 []；choice 型无空走子 → None（超时直接判负）
        self.pvp_empty_action = [] if pvp_meta.get("action") == "unit" else None
        # v2（12 §3）：PvP 开局附加参数（如 microrts {opponent: external}）
        self.pvp_options = pvp_meta.get("options")
        # v2（12 §3）：PvE 服务端对手声明（sessions 通用化用）
        self.opponents = meta.get("opponents") or []
        self.default_opponent = meta.get("default_opponent")
        # 仅声明 ai_strategies 才挂载 /ai/action（否则 has_ai 误报、端点报错）
        self.ai_request_model = UGCAIRequest if (meta.get("ai_strategies") or []) else None
        self._on_unhealthy = on_unhealthy
        self._info = None
        self._bounds = None

    def _worker(self) -> ugc_runner.GameWorker:
        return ugc_runner.get_worker(self.game_id, self.game_dir,
                                     on_unhealthy=self._on_unhealthy)

    # -------------------------------------------------------- EnvAdapter face
    def info(self) -> dict:
        if self._info is None:
            base = self._worker().request("info")
            if not isinstance(base, dict):
                base = {}
            bw = self.meta["board"]["width"]
            bh = self.meta["board"]["height"]
            base.setdefault("grid", [bw, bh])
            self._info = base
        return self._info

    @property
    def score_bounds(self) -> tuple[int, int]:
        if self._bounds is None:
            lo, hi = self._worker().request("score_bounds")
            self._bounds = (int(lo), int(hi))
        return self._bounds

    def new_state(self, seed, options=None):
        return self._worker().request("new_state", seed=int(seed),
                                      options=options)

    def new_batch(self, seeds, options=None, obs_mode=None):
        return self._worker().request("new_batch", seeds=seeds, options=options,
                                      obs_mode=obs_mode, timeout=min(5., max(.2, len(seeds) * .02)))

    def step_batch(self, states, actions, rewards=None, obs_mode=None):
        return self._worker().request("step_batch", states=states, actions=actions,
                                      rewards=rewards, obs_mode=obs_mode,
                                      timeout=min(5., max(.2, len(states) * .02)))

    def step_state(self, state, action, rewards=None):
        return self._worker().request("step_state", state=state,
                                      action=action, rewards=rewards)

    def validate_state(self, state):
        # 契约约定校验失败抛 ValueError；把沙箱错误翻译回来（13 G3）
        try:
            return self._worker().request("validate_state", state=state)
        except ugc_runner.WorkerError as e:
            raise ValueError(str(e))

    def validate_action(self, action, state=None):
        try:
            return self._worker().request("validate_action", action=action,
                                          state=state)
        except ugc_runner.WorkerError as e:
            raise ValueError(str(e))

    def opponent_action(self, state, config):
        return self._worker().request("opponent_action", state=state,
                                      config=config)

    def ai_action(self, payload: dict):
        return self._worker().request("ai_action", payload=payload)

    def sample_action(self, state):
        return self._worker().request("sample_action", state=state)

    def obs(self, state, mode=None):
        return self._worker().request("obs", state=state, mode=mode)

    def model_inputs(self, state, owner=0):
        return self._worker().request("model_inputs", state=state, owner=owner)

    def model_decode(self, outputs, state, owner=0):
        return self._worker().request("model_decode", outputs=outputs,
                                     state=state, owner=owner)
