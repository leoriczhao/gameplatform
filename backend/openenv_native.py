"""OpenEnv is the sole public environment interaction protocol.

One WebSocket connection owns one environment. Episode configuration (version,
options, obs_mode, rewards, include_state) is selected at reset; step receives
only an action. The existing package engines are reused, not exposed as a
stateless HTTP transition API. See docs/api/openenv.md for the wire contract.

Import-time proxy masking below avoids a gradio/httpx issue in environments
whose NO_PROXY contains an unbracketed IPv6 entry.
"""
from __future__ import annotations

import asyncio
import functools
import os
import threading
from typing import Annotated, Any, Literal, Type

import numpy as np
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import Field, WithJsonSchema, create_model

import registry
from api_limits import rate_limit
from environment_contract import (
    checked_rewards, describe_environment, environment_schemas,
)

# ------------------------------------------------------------------ 常量

DEFAULT_SPLIT = "default"   # task split：seed 序列（v1 语义，兼容 ORS 形状）
MAX_TASKS = 10_000          # task = seed 序列长度
MAX_WS_SESSIONS = 64        # 每游戏并发 WebSocket 会话上限（官方 max_concurrent_envs）
DEFAULT_SEED = 0            # reset 未传 seed 时的默认种子（确定性；显式传 seed 可复现）

# httpx 0.28.1 解析 env 代理的键；导入 openenv 时临时摘除（见模块 docstring）
_PROXY_ENV_KEYS = (
    "HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
    "ALL_PROXY", "all_proxy", "NO_PROXY", "no_proxy", "NODE_USE_ENV_PROXY",
)


def _import_openenv():
    """导入官方 openenv 包（临时摘除代理环境变量，详见模块 docstring）。"""
    saved = {k: os.environ.pop(k) for k in _PROXY_ENV_KEYS if k in os.environ}
    try:
        from openenv.core.env_server import (  # noqa: F401
            Action, Environment, Observation, State, create_fastapi_app,
        )
        # EnvironmentMetadata / SchemaResponse 未在 env_server.__all__ 导出：
        from openenv.core.env_server.types import (  # noqa: F401
            EnvironmentMetadata, SchemaResponse,
        )
    finally:
        os.environ.update(saved)
    return (Action, Environment, EnvironmentMetadata, Observation, State,
            SchemaResponse, create_fastapi_app)


(Action, Environment, EnvironmentMetadata, Observation, State,
 SchemaResponse, create_fastapi_app) = _import_openenv()

# ------------------------------------------------------------------ wire 模型


class PlatformAction(Action):
    """官方 OpenEnv 动作信封（兜底）：{"value": <原始动作>}。"""

    value: Any = Field(
        ...,
        description="Game action (raw int/list/dict; see environment.schemas.action)")


class PlatformObservation(Observation):
    """归一化观测：服务端 tensor，或 state 透传回退。"""

    type: Literal["tensor", "state"] = "tensor"
    data: Any = None
    shape: list[int] | None = None
    dtype: str | None = None
    state: Any = None


class PlatformState(State):
    """Session inspection, including the pinned package description.

    game_state is available for the current snapshot-based game adapters. It
    is not required to be the observation supplied to a training policy.
    """

    game_state: dict | None = None
    environment: dict = Field(default_factory=dict)


def make_action_cls(game_id: str, value_schema: dict | None) -> Type[Action]:
    """按游戏 schemas.action 动态生成官方 Action 子类（/schema.action 展示真实形状）。

    schema 缺失/无法建模时回退泛型 PlatformAction（运行期仍由 validate_action 校验）。
    """
    if not isinstance(value_schema, dict) or not value_schema:
        return PlatformAction
    try:
        return create_model(
            f"{game_id.capitalize()}Action",
            __base__=Action,
            value=(Annotated[Any, WithJsonSchema(value_schema)],
                   Field(..., description="Game action as declared by environment.schemas.action")),
        )
    except Exception:
        return PlatformAction


# ------------------------------------------------------------------ 环境


class PlatformEnvironment(Environment[Action, PlatformObservation, PlatformState]):
    """One session-owned game episode, backed by the existing package engine.

    HTTP calls create ephemeral instances in the official server. A persistent
    WebSocket (or an explicit MCP session) is required to reset then step.
    """

    # 会话实例之间无共享可变状态（各持一份 state dict），可并发
    SUPPORTS_CONCURRENT_SESSIONS = True

    def __init__(self, game_id: str):
        super().__init__()
        self.game_id = game_id
        self._game_state: dict | None = None
        self._seed: int | None = None
        self._episode_id: str | None = None
        self._step_count = 0
        self._obs_mode: str | None = None
        self._include_state = False
        self._rewards: dict = {}
        self._frozen_adapter = None  # 本会话绑定的游戏包版本
        self._mcp_server = None      # 懒构建的 FastMCP 工具面
        self._tool_lock = threading.Lock()  # MCP 工具调用串行化

    # ------------------------------------------------------ 适配器与工具
    def _current(self):
        """Registry lookup — 下架/暂停/熔断后必须中止会话。"""
        cur = registry.GAMES.get(self.game_id)
        if cur is None:
            raise RuntimeError(f"game {self.game_id!r} is unavailable")
        return cur

    def _adapter(self):
        """会话内冻结版本；reset 前的环境描述使用当前版本。

        发布/回滚会原地覆盖 registry.GAMES[slug]；若每次 step 都重新解析，
        一个 WS 会话可能前半局 v1、后半局 v2，破坏"同 seed 同轨迹"。
        reset 时冻结，既保证会话内版本一致，又通过 _current() 保留下架语义。
        """
        if self._frozen_adapter is not None:
            self._current()  # 可用性守卫：下架/熔断 -> RuntimeError
            return self._frozen_adapter
        return self._current()

    def _describe(self, cur) -> dict:
        return describe_environment(cur, max_concurrent_envs=MAX_WS_SESSIONS)

    def _pack_meta(self, state: dict, *, step_count: int | None = None) -> dict:
        meta: dict[str, Any] = {}
        for key in ("score", "cause", "tick", "lines", "ate"):
            if key in state:
                meta[key] = state[key]
        if self._seed is not None:
            meta["seed"] = self._seed
        if self._episode_id is not None:
            meta["episode_id"] = self._episode_id
        if step_count is not None:
            meta["step_count"] = step_count
        return meta

    def _pack_obs(self, cur, state: dict, meta: dict, reward,
                  done: bool) -> PlatformObservation:
        if self._obs_mode is not None:
            obs = cur.obs(state, self._obs_mode)
            if obs is None:
                raise ValueError(f"observation mode {self._obs_mode!r} returned no data")
            arr = np.asarray(obs, dtype=np.float32)
            return PlatformObservation(
                type="tensor", data=arr.tolist(),
                shape=list(arr.shape), dtype=str(arr.dtype),
                state=state if self._include_state else None,
                reward=reward, done=done, metadata=meta)
        return PlatformObservation(
            type="state", state=state,
            reward=reward, done=done, metadata=meta)

    @staticmethod
    def _coerce_reward(reward) -> float | None:
        if reward is None:
            return None
        try:
            return float(reward)
        except (TypeError, ValueError):
            return None

    # ---------------------------------------------------------- MCP 工具面
    # 官方 HTTPEnvServer 在环境实例上查找 mcp_server（FastMCP），把 JSON-RPC
    # tools/list + tools/call 路由过来；会话用 openenv/session/{create,close}，
    # tools/call 带 session_id 时状态跨调用保持。保留名 reset/step/state/close。
    @property
    def mcp_server(self):
        if self._mcp_server is None:
            self._mcp_server = self._build_mcp_server()
        return self._mcp_server

    def _build_mcp_server(self):
        from fastmcp import FastMCP
        mcp = FastMCP(f"gameplatform-{self.game_id}")

        @mcp.tool()
        async def describe() -> dict:
            """Environment metadata: action space, observation modes, schemas."""
            return await self._mcp_call(self._tool_describe)

        @mcp.tool()
        async def new_episode(seed: int = 0, options: dict | None = None,
                              version: str | None = None, obs_mode: str | None = None,
                              rewards: dict | None = None, include_state: bool = False) -> dict:
            """Start a configured episode; version pins an archived package."""
            return await self._mcp_call(self._tool_reset, seed, options,
                                        version, obs_mode, rewards, include_state)

        @mcp.tool()
        async def observe() -> dict:
            """Current state of this session's episode."""
            return await self._mcp_call(self._tool_observe)

        @mcp.tool()
        async def act(action: Any) -> dict:
            """Apply one game action (int / command list / dict) to the episode."""
            return await self._mcp_call(self._tool_act, action)

        return mcp

    async def _mcp_call(self, fn, *args) -> dict:
        """Run a blocking game transition off the event loop."""
        return await asyncio.to_thread(fn, *args)

    def _tool_describe(self) -> dict:
        return self._describe(self._adapter())

    def _tool_reset(self, seed: int, options: dict | None,
                    version: str | None = None, obs_mode: str | None = None,
                    rewards: dict | None = None, include_state: bool = False) -> dict:
        with self._tool_lock:
            obs = self.reset(seed=seed, options=options, version=version,
                             obs_mode=obs_mode, rewards=rewards, include_state=include_state)
            return self._tool_payload(obs)

    def _tool_observe(self) -> dict:
        with self._tool_lock:
            if self._game_state is None:
                raise ValueError("no active episode: call new_episode first")
            return {"state": self._game_state,
                    "reward": self._coerce_reward(self._game_state.get("reward")),
                    "done": bool(self._game_state.get("done", False)),
                    "step_count": self._step_count,
                    "metadata": self._pack_meta(self._game_state,
                                               step_count=self._step_count)}

    def _tool_act(self, action: Any) -> dict:
        with self._tool_lock:
            return self._tool_payload(self.step(PlatformAction(value=action)))

    def _tool_payload(self, obs: PlatformObservation) -> dict:
        return {"state": self._game_state,
                "reward": obs.reward,
                "done": bool(obs.done),
                "step_count": self._step_count,
                "metadata": obs.metadata}

    # ------------------------------------------------------ Environment 接口
    def reset(self, seed: int | None = None, episode_id: str | None = None,
              *, version: str | None = None, options: dict | None = None,
              obs_mode: str | None = None, rewards: dict | None = None,
              include_state: bool = False, **kwargs: Any) -> PlatformObservation:
        """Start an episode with fixed version, observation and reward settings."""
        self._current()  # archived versions do not bypass unpublish/pause
        try:
            cur = registry.resolve(self.game_id, version)
        except registry.VersionUnavailable as exc:
            raise ValueError(str(exc)) from exc
        seed = DEFAULT_SEED if seed is None else seed
        if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
            raise ValueError("seed must be a non-negative integer")
        if options is not None and not isinstance(options, dict):
            raise ValueError("options must be an object")
        if not isinstance(include_state, bool):
            raise ValueError("include_state must be a boolean")
        modes = (cur.info() or {}).get("obs_modes") or []
        if obs_mode is None:
            mode = modes[0] if modes else None
        elif obs_mode == "state":
            mode = None
        elif isinstance(obs_mode, str) and obs_mode in modes:
            mode = obs_mode
        else:
            raise ValueError(f"unknown obs_mode {obs_mode!r} (available: {modes + ['state']})")
        configured_rewards = checked_rewards(cur.info() or {}, rewards)
        # Validate official episode metadata before changing the active episode.
        State(episode_id=episode_id, step_count=0)
        state = cur.new_state(seed, options)
        self._frozen_adapter = cur
        self._obs_mode = mode
        self._include_state = include_state
        self._rewards = configured_rewards
        self._game_state = state
        self._seed = seed
        self._episode_id = episode_id
        self._step_count = 0
        reward = self._coerce_reward(state.get("reward"))
        meta = self._pack_meta(state, step_count=0)
        meta["environment"] = self._describe(cur)
        if reward is not None:
            meta["initial_reward"] = reward
        return self._pack_obs(cur, state, meta, reward, bool(state.get("done", False)))

    def step(self, action: Action, timeout_s: float | None = None,
             **kwargs: Any) -> PlatformObservation:
        """Advance the session using only {"value": <game action>}."""
        cur = self._adapter()
        if self._game_state is None:
            raise ValueError("no active episode: reset on the same WebSocket or MCP session first")
        raw = getattr(action, "value", None)
        cur.validate_action(raw, self._game_state)
        nxt = cur.step_state(self._game_state, raw, self._rewards)
        self._game_state = nxt
        self._step_count += 1
        reward = self._coerce_reward(nxt.get("reward", 0.0))
        meta = self._pack_meta(nxt, step_count=self._step_count)
        return self._pack_obs(cur, nxt, meta, reward, bool(nxt.get("done", False)))

    @property
    def state(self) -> PlatformState:
        """Inspect this session and its exact package version (also before reset)."""
        # Must return PlatformState (not bare State with extras): create_fastapi_app
        # registers GET /state with response_model=State, and FastAPI drops subclass
        # fields when coercing PlatformState -> State. Extras on State work for that
        # route, but WS clients and schema should see declared game_state/environment.
        # make_openenv_app re-registers /state with response_model=PlatformState.
        return PlatformState(
            episode_id=self._episode_id, step_count=self._step_count,
            game_state=self._game_state, environment=self._describe(self._adapter()))

    def get_metadata(self) -> EnvironmentMetadata:
        cur = self._adapter()
        info = cur.info() or {}
        meta = getattr(cur, "meta", None) or {}
        desc = info.get("notes") or info.get("deterministic") or ""
        if isinstance(desc, bool):
            desc = ""
        return EnvironmentMetadata(
            name=getattr(cur, "name", self.game_id),
            description=(f"{info.get('name') or self.game_id}: "
                         f"{info.get('action_space', '')} · obs_modes={info.get('obs_modes')} · "
                         f"确定性子句：{desc}"[:500]),
            version=str(meta["version"]) if meta.get("version") is not None else None,
            author=getattr(cur, "author", None) or "未知",
            documentation_url=f"/api/openenv/{self.game_id}/schema",
        )

    def close(self) -> None:
        # The package worker is shared with other training/play sessions. Only
        # release this episode; never kill the shared worker on socket close.
        self._game_state = None
        self._frozen_adapter = None
        self._seed = None
        self._episode_id = None
        self._step_count = 0
        self._rewards = {}
        self._obs_mode = None
        self._include_state = False
        self._mcp_server = None

    # ------------------------------------------------------ TaskProvider（ORS 形状）
    @staticmethod
    def _task_spec(index: int) -> dict:
        return {"index": index, "seed": index}

    def list_splits(self) -> list[dict]:
        return [{"name": DEFAULT_SPLIT, "type": "validation"}]

    def _check_split(self, split: str) -> None:
        # IndexError -> 官方 _call_task_method 转 400（Invalid task index）
        if split != DEFAULT_SPLIT:
            raise IndexError(f"unknown split {split!r} (available: {DEFAULT_SPLIT})")

    def list_tasks(self, split: str) -> list[dict]:
        self._check_split(split)
        return [self._task_spec(i) for i in range(MAX_TASKS)]

    def num_tasks(self, split: str) -> int:
        self._check_split(split)
        return MAX_TASKS

    def get_task(self, split: str, index: int) -> dict:
        self._check_split(split)
        if not 0 <= index < MAX_TASKS:
            raise IndexError(f"invalid task index (0..{MAX_TASKS - 1})")
        return self._task_spec(index)

    def get_task_range(self, split: str, start: int | None = None,
                       stop: int | None = None) -> list[dict]:
        self._check_split(split)
        start = 0 if start is None else max(0, min(int(start), MAX_TASKS))
        stop = (start + 1) if stop is None else max(start, min(int(stop), MAX_TASKS))
        return [self._task_spec(i) for i in range(start, stop)]


# ------------------------------------------------------------------ 服务器工厂


def make_openenv_app(game_id: str) -> FastAPI:
    """为单个游戏构建官方 OpenEnv FastAPI 子应用（挂载于 /api/openenv/{game_id}）。"""
    cur = registry.GAMES.get(game_id)
    value_schema = None
    if cur is not None:
        info = cur.info() or {}
        value_schema = (environment_schemas(info)).get("action")
    action_cls = make_action_cls(game_id, value_schema)

    app = create_fastapi_app(
        functools.partial(PlatformEnvironment, game_id),
        action_cls,
        PlatformObservation,
        max_concurrent_envs=MAX_WS_SESSIONS,
        env_name=game_id,
    )

    # /schema 动态化：官方在挂载时按当时版本生成；版本切换后必须反映当前版本。
    # /state 换成 PlatformState：官方 create_fastapi_app 用 response_model=State，
    # 会把 PlatformState 的 game_state/environment 剥掉，只剩 episode_id/step_count。
    app.router.routes[:] = [
        r for r in app.router.routes
        if getattr(r, "path", None) not in ("/schema", "/state")
    ]

    @app.get("/state", response_model=PlatformState, tags=["State Management"])
    def _platform_state() -> PlatformState:
        env = PlatformEnvironment(game_id)
        try:
            return env.state
        finally:
            env.close()

    @app.get("/schema", response_model=SchemaResponse, tags=["Environment Info"])
    async def _dynamic_schema() -> SchemaResponse:
        cur_now = registry.GAMES.get(game_id)
        if cur_now is None:
            raise HTTPException(404, f"unknown game {game_id!r}")
        action_schema = environment_schemas(cur_now.info() or {}).get("action")
        return SchemaResponse(
            action=make_action_cls(game_id, action_schema).model_json_schema(),
            observation=PlatformObservation.model_json_schema(),
            state=PlatformState.model_json_schema(),
        )

    @app.exception_handler(ValueError)
    async def _value_error(_request: Request, exc: ValueError) -> JSONResponse:
        # 非法动作 / 版本不可用等契约错误 -> 400（官方默认会落成 500）
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.middleware("http")
    async def _game_guard(request: Request, call_next):
        # 游戏下架/暂停/熔断 -> OpenEnv HTTP 面整体 404
        if registry.GAMES.get(game_id) is None:
            return JSONResponse(status_code=404,
                                content={"detail": f"unknown game {game_id!r}"})
        return await call_next(request)

    @app.middleware("http")
    async def _env_rate_limit(request: Request, call_next):
        # HTTP inspection/reset calls have a request budget; WebSocket
        # training is bounded separately by the official session capacity.
        operation = request.url.path.rstrip("/").rsplit("/", 1)[-1]
        if request.method == "POST" and operation in ("reset", "step"):
            try:
                rate_limit(request)
            except HTTPException:
                return JSONResponse(status_code=429,
                                    content={"detail": "env API rate limit exceeded"})
        return await call_next(request)

    return app
