"""OpenEnv 官方接入测试（docs/design/15 v2：官方 openenv==0.4.1 栈）。

覆盖：官方 wire 形状（/schema /metadata /health /state /reset /step /tasks*）、
WS 与内部游戏引擎逐位一致、配置与元数据、官方错误帧、旧无状态接口移除、
复合动作通道、历史版本与资源生命周期。
"""
import os
import sys
import tempfile
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

_tmp = tempfile.TemporaryDirectory()
os.environ["SCORES_DB"] = str(Path(_tmp.name) / "scores.db")
os.environ["MODELS_DIR"] = str(Path(_tmp.name) / "models")

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
import openenv_native  # noqa: E402
import registry  # noqa: E402
import api_limits  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_http_limits():
    api_limits._hits.clear()

client = TestClient(main.app)

OENV = "/api/openenv"


def _engine_new(game: str, seed: int) -> dict:
    return registry.GAMES[game].new_state(seed)


def _engine_step(game: str, state: dict, action) -> dict:
    adapter = registry.GAMES[game]
    nxt = adapter.step_state(state, action, adapter.info().get("default_rewards") or {})
    return {"state": nxt, "reward": nxt.get("reward", 0.0), "done": nxt.get("done", False)}


# ------------------------------------------------------------------ HTTP 官方形状


def test_list_environments():
    r = client.get(f"{OENV}/list_environments")
    assert r.status_code == 200
    assert set(r.json()) == {"snake", "tetris", "microrts"}


def test_official_schema_shape():
    r = client.get(f"{OENV}/tetris/schema")
    assert r.status_code == 200
    body = r.json()
    # 官方 SchemaResponse：action/observation/state 三份 JSON Schema
    assert set(body) == {"action", "observation", "state"}
    assert body["action"]["required"] == ["value"]
    # 每个游戏的 Action 由游戏包 schemas.action 动态生成（真实动作形状）
    assert "type" in body["action"]["properties"]["value"]
    assert set(body["observation"]["properties"]) >= {"type", "data", "shape", "dtype"}
    assert body["state"]["type"] == "object"


def test_metadata_health_state():
    m = client.get(f"{OENV}/tetris/metadata").json()
    assert m["name"]
    assert m["description"]
    assert "version" in m and "author" in m
    h = client.get(f"{OENV}/tetris/health").json()
    assert h == {"status": "healthy"}
    # 官方 simulation 模式有 GET /state（会话元状态）
    s = client.get(f"{OENV}/tetris/state").json()
    assert set(s) == {"episode_id", "step_count", "game_state", "environment"}
    assert s["game_state"] is None
    assert s["environment"]["game"] == "tetris"
    assert s["environment"]["max_concurrent_envs"] == 64
    assert m["documentation_url"] == f"{OENV}/tetris/schema"


def test_reset_deterministic_and_observation_tensor():
    a = client.post(f"{OENV}/tetris/reset", json={"seed": 42}).json()
    b = client.post(f"{OENV}/tetris/reset", json={"seed": 42}).json()
    assert a["observation"] == b["observation"]
    obs = a["observation"]
    assert obs["type"] == "tensor"
    assert obs["shape"] == [2, 20, 10]
    assert obs["dtype"] == "float32"
    assert a["done"] is False
    assert a["metadata"]["seed"] == 42
    assert "metadata" in obs  # 嵌套在 observation 里同时保留（官方 serialize 语义）


def test_ws_step_parity_with_engine():
    state = _engine_new("tetris", 11)
    with client.websocket_connect(f"{OENV}/tetris/ws") as ws:
        ws.send_json({"type": "reset", "data": {"seed": 11, "include_state": True}})
        assert ws.receive_json()["data"]["observation"]["state"] == state
        for action in (2, 0, 3, 1, 3):
            ws.send_json({"type": "step", "data": {"value": action}})
            oe = ws.receive_json()["data"]
            expected = _engine_step("tetris", state, action)
            assert oe["reward"] == expected["reward"]
            assert oe["done"] == expected["done"]
            assert oe["observation"]["state"] == expected["state"]
            state = expected["state"]


def test_http_step_does_not_inherit_reset_or_accept_state_injection():
    r = client.post(f"{OENV}/tetris/reset", json={"seed": 11, "include_state": True})
    assert r.status_code == 200
    state = r.json()["observation"]["state"]
    for value in (3, {"state": state, "action": 3}):
        result = client.post(f"{OENV}/tetris/step", json={"action": {"value": value}})
        assert result.status_code == 400, result.text
        assert "same WebSocket" in result.json()["detail"]


def test_tasks_endpoints():
    # 官方 Task API 形状（ORS 兼容）：/{env_name}/tasks* 在子应用内
    assert client.get(f"{OENV}/tetris/tetris/splits").json() == [
        {"name": "default", "type": "validation"}]
    assert client.get(f"{OENV}/tetris/list_environments").json() == ["tetris"]
    assert client.post(f"{OENV}/tetris/tetris/num_tasks",
                       json={"split": "default"}).json()["num_tasks"] == 10_000
    t = client.post(f"{OENV}/tetris/tetris/task",
                    json={"split": "default", "index": 5}).json()
    assert t["task"] == {"index": 5, "seed": 5}
    ts = client.post(f"{OENV}/tetris/tetris/task_range",
                     json={"split": "default", "start": 7, "stop": 9}).json()["tasks"]
    assert ts == [{"index": 7, "seed": 7}, {"index": 8, "seed": 8}]
    assert client.post(f"{OENV}/tetris/tetris/task",
                       json={"split": "nope", "index": 0}).status_code == 400
    lst = client.post(f"{OENV}/tetris/tetris/tasks",
                      json={"split": "default"}).json()
    assert lst["env_name"] == "tetris"
    assert len(lst["tasks"]) == 10_000 and lst["tasks"][0] == {"index": 0, "seed": 0}
    assert client.get(f"{OENV}/tetris/nope/splits").status_code == 404


# ------------------------------------------------------------------ WS 会话（官方协议）


def test_ws_tetris_session_official_protocol():
    with client.websocket_connect(f"{OENV}/tetris/ws") as ws:
        ws.send_json({"type": "reset", "data": {"seed": 31, "episode_id": "e1"}})
        msg = ws.receive_json()
        assert msg["type"] == "observation"
        d = msg["data"]
        assert d["observation"]["type"] == "tensor"
        assert d["observation"]["metadata"]["episode_id"] == "e1"
        for a in (2, 3, 2, 3):
            ws.send_json({"type": "step", "data": {"value": a}})
            d2 = ws.receive_json()
            assert d2["type"] == "observation"
            assert d2["data"]["observation"]["metadata"]["step_count"] in (1, 2, 3, 4)
        ws.send_json({"type": "state"})
        st = ws.receive_json()
        assert st["type"] == "state"
        assert st["data"]["episode_id"] == "e1"
        assert st["data"]["step_count"] == 4
        ws.send_json({"type": "close"})


def test_ws_parity_with_snake_engine():
    acts = [1, 1, 0, 1, 2, 1, 0, 2, 1, 1]
    with client.websocket_connect(f"{OENV}/snake/ws") as ws:
        ws.send_json({"type": "reset", "data": {"seed": 5}})
        assert ws.receive_json()["type"] == "observation"
        last = None
        for a in acts:
            ws.send_json({"type": "step", "data": {"value": a}})
            last = ws.receive_json()
        ws.send_json({"type": "close"})
    s = _engine_new("snake", 5)
    native_last = None
    for a in acts:
        native_last = _engine_step("snake", s, a)
        s = native_last["state"]
    obs_meta = last["data"]["observation"]["metadata"]
    assert obs_meta["tick"] == native_last["state"]["tick"]
    assert obs_meta["score"] == native_last["state"]["score"]
    assert last["data"]["done"] == native_last["done"]


def test_ws_errors():
    with client.websocket_connect(f"{OENV}/tetris/ws") as ws:
        ws.send_json({"type": "step", "data": {"value": 3}})
        e = ws.receive_json()
        assert e["type"] == "error" and e["data"]["code"] == "EXECUTION_ERROR"
        ws.send_json({"type": "reset", "data": {"seed": 0}})
        ws.receive_json()
        ws.send_json({"type": "step", "data": {"value": "bad"}})
        e2 = ws.receive_json()
        assert e2["data"]["code"] == "EXECUTION_ERROR"
        ws.send_json({"type": "???", "data": {}})
        assert ws.receive_json()["data"]["code"] == "UNKNOWN_TYPE"
        ws.send_text("{bad json")
        assert ws.receive_json()["data"]["code"] == "INVALID_JSON"
        ws.send_json({"type": "close"})


def test_ws_microrts_composite_action():
    """microrts 复合动作经官方信封 {"value": <commands>} 通道直通。"""
    with client.websocket_connect(f"{OENV}/microrts/ws") as ws:
        ws.send_json({"type": "reset", "data": {"seed": 3}})
        assert ws.receive_json()["data"]["observation"]["type"] == "tensor"
        ws.send_json({"type": "step", "data": {"value": []}})
        d = ws.receive_json()["data"]
        assert d["done"] in (True, False)
        ws.send_json({"type": "step", "data": {"value": []}})
        d2 = ws.receive_json()["data"]
        assert d2["observation"]["metadata"]["step_count"] == 2
        ws.send_json({"type": "close"})


class _FakeAdapter:
    """最小 EnvAdapter：n 每步增加 step_inc，用来区分两个版本。"""

    def __init__(self, game_id: str, step_inc: int, version: str = "1.0.0"):
        self.game_id = game_id
        self.name = game_id
        self.meta = {"version": version}
        self.score_bounds = (0, 100)
        self._inc = step_inc

    def info(self):
        return {"grid": [4, 4], "obs_modes": []}

    def new_state(self, seed, options=None):
        return {"tick": 0, "done": False, "n": 0, "seed": int(seed)}

    def step_state(self, state, action, rewards=None):
        return dict(state, tick=state["tick"] + 1, n=state["n"] + self._inc)

    def validate_state(self, state):
        return None

    def validate_action(self, action, state):
        return None


def test_session_freezes_its_package_version():
    """版本发布覆盖注册表后，进行中的会话必须继续用旧版本。"""
    slug = "freeze-test"
    registry.GAMES[slug] = _FakeAdapter(slug, step_inc=1)
    try:
        env = openenv_native.PlatformEnvironment(slug)
        first = env.reset(seed=0)
        assert first.state["n"] == 0
        # 新版本发布：注册表被原地覆盖
        registry.GAMES[slug] = _FakeAdapter(slug, step_inc=100)
        obs = env.step(openenv_native.PlatformAction(value=0))
        assert obs.state["n"] == 1        # 旧版本 +1，而不是新版本 +100
        assert obs.metadata["step_count"] == 1
        # 新会话拿到新版本
        fresh = openenv_native.PlatformEnvironment(slug)
        fresh.reset(seed=0)
        assert fresh.step(
            openenv_native.PlatformAction(value=0)).state["n"] == 100
        # 下架/熔断仍然中止进行中的会话
        registry.GAMES.pop(slug)
        with pytest.raises(RuntimeError):
            env.step(openenv_native.PlatformAction(value=0))
    finally:
        registry.GAMES.pop(slug, None)


def _mcp(method: str, params: dict | None = None, req_id: int = 1) -> dict:
    body: dict = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params is not None:
        body["params"] = params
    r = client.post(f"{OENV}/snake/mcp", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_mcp_tools_list_exposes_game_tools():
    tools = _mcp("tools/list")["result"]["tools"]
    names = {t["name"] for t in tools}
    assert {"describe", "new_episode", "observe", "act"} <= names
    assert not names & {"reset", "step", "state", "close"}  # 官方保留名
    act = next(t for t in tools if t["name"] == "act")
    assert "inputSchema" in act


def test_mcp_stateful_session_plays_the_game():
    sid = _mcp("openenv/session/create")["result"]["session_id"]
    try:
        d = _mcp("tools/call", {"name": "describe",
                                "session_id": sid})["result"]
        assert d["game"] == "snake"
        assert d["schemas"]["action"]["enum"] == [0, 1, 2]
        r = _mcp("tools/call", {"name": "new_episode",
                                "arguments": {"seed": 7},
                                "session_id": sid})["result"]
        assert r["state"]["seed"] == 7 and r["step_count"] == 0
        r = _mcp("tools/call", {"name": "act", "arguments": {"action": 1},
                                "session_id": sid})["result"]
        assert r["state"]["tick"] == 1 and r["step_count"] == 1
        r = _mcp("tools/call", {"name": "observe",
                                "session_id": sid})["result"]
        assert r["state"]["tick"] == 1
    finally:
        _mcp("openenv/session/close", {"session_id": sid})


def test_mcp_without_session_is_stateless_and_rejects_unknown_tools():
    r = _mcp("tools/call", {"name": "act", "arguments": {"action": 1}})
    assert "error" in r  # 每次调用新建实例，没有 episode
    r = _mcp("tools/call", {"name": "nope"})
    assert "error" in r and "not found" in r["error"]["message"].lower()


def test_games_catalog_exposes_openenv_url():
    games = client.get("/api/games").json()["games"]
    assert games
    assert all(g["openenv_url"] == f"/api/openenv/{g['id']}" for g in games)
    assert all(g["schema_url"] == g["openenv_url"] + "/schema" for g in games)
    assert all("env_info_url" not in g for g in games)


def test_schema_follows_the_current_version():
    """版本切换后 /schema 必须反映当前版本（不能是挂载时的快照）。"""
    real = registry.GAMES["snake"]

    class _Wide:
        def __init__(self, inner):
            self._inner = inner
            self.game_id = inner.game_id
            self.name = inner.name
            self.meta = inner.meta
            self.score_bounds = inner.score_bounds

        def info(self):
            info = dict(self._inner.info())
            info["schemas"] = dict(info["schemas"])
            info["schemas"]["action"] = {"type": "integer",
                                         "enum": [0, 1, 2, 3]}
            return info

        def __getattr__(self, name):
            return getattr(self._inner, name)

    def _enum():
        return client.get(f"{OENV}/snake/schema").json()["action"][
            "properties"]["value"]["enum"]

    try:
        assert _enum() == [0, 1, 2]
        registry.GAMES["snake"] = _Wide(real)
        assert _enum() == [0, 1, 2, 3]
    finally:
        registry.GAMES["snake"] = real


def test_invalid_action_does_not_advance_the_session():
    with client.websocket_connect(f"{OENV}/snake/ws") as ws:
        ws.send_json({"type": "reset", "data": {"seed": 0, "obs_mode": "state"}})
        initial = ws.receive_json()["data"]["observation"]["state"]
        ws.send_json({"type": "step", "data": {"value": 9}})
        assert ws.receive_json()["type"] == "error"
        ws.send_json({"type": "state"})
        current = ws.receive_json()["data"]
        assert current["step_count"] == 0
        assert current["game_state"] == initial


def test_reset_pins_archived_version(monkeypatch):
    """WS reset 的 version 字段钉住已审核版本；缺省用当前版本。"""
    slug = "pin-test"
    v1 = _FakeAdapter(slug, step_inc=1, version="1.0.0")
    v2 = _FakeAdapter(slug, step_inc=100, version="2.0.0")
    registry.GAMES[slug] = v2

    import ugc

    def _version_adapter(game, version):
        if version == "1.0.0":
            return v1
        raise registry.VersionUnavailable(
            f"game {game!r} version {version!r} is unavailable")

    monkeypatch.setattr(ugc, "version_adapter", _version_adapter)
    main._mount_ugc_routes(v2)
    try:
        with client.websocket_connect(f"{OENV}/{slug}/ws") as ws:
            ws.send_json({"type": "reset",
                          "data": {"seed": 0, "version": "1.0.0"}})
            ws.receive_json()
            ws.send_json({"type": "step", "data": {"value": 0}})
            d = ws.receive_json()["data"]
            assert d["observation"]["state"]["n"] == 1  # v1 的 +1
            ws.send_json({"type": "close"})
        with client.websocket_connect(f"{OENV}/{slug}/ws") as ws:
            ws.send_json({"type": "reset", "data": {"seed": 0}})
            ws.receive_json()
            ws.send_json({"type": "step", "data": {"value": 0}})
            d = ws.receive_json()["data"]
            assert d["observation"]["state"]["n"] == 100  # 当前版本 v2
            ws.send_json({"type": "close"})
        with client.websocket_connect(f"{OENV}/{slug}/ws") as ws:
            ws.send_json({"type": "reset",
                          "data": {"seed": 0, "version": "9.9.9"}})
            msg = ws.receive_json()
            assert msg["type"] == "error"
            ws.send_json({"type": "close"})
    finally:
        registry.GAMES.pop(slug, None)


def test_unregistered_game_404():
    """下架/熔断（registry.unregister）后，OpenEnv 面整体 404。"""
    adapter = registry.GAMES["snake"]
    assert client.get(f"{OENV}/snake/schema").status_code == 200
    registry.unregister("snake")
    try:
        assert client.get(f"{OENV}/snake/schema").status_code == 404
        assert client.post(f"{OENV}/snake/reset",
                           json={"seed": 1}).status_code == 404
    finally:
        registry.register(adapter, source="builtin")
    assert client.get(f"{OENV}/snake/schema").status_code == 200


@pytest.mark.parametrize("obs_mode,include_state,kind", [
    ("grid", False, "tensor"), ("grid", True, "tensor"), ("state", False, "state"),
])
def test_episode_observation_and_reward_configuration(obs_mode, include_state, kind):
    with client.websocket_connect(f"{OENV}/tetris/ws") as ws:
        ws.send_json({"type": "state"})
        before = ws.receive_json()["data"]
        assert before["game_state"] is None
        version = before["environment"]["version"]
        ws.send_json({"type": "reset", "data": {
            "seed": 13, "version": version, "obs_mode": obs_mode,
            "include_state": include_state, "rewards": {"step": 0.125},
        }})
        first = ws.receive_json()["data"]["observation"]
        assert first["type"] == kind
        environment = first["metadata"]["environment"]
        assert environment["version"] == version
        assert environment["meta"]["version"] == version
        assert environment["schemas"]["action"]["enum"] == [0, 1, 2, 3]
        assert "max_batch" not in environment
        ws.send_json({"type": "step", "data": {"value": 3}})
        result = ws.receive_json()["data"]
        assert result["reward"] == 0.125
        obs = result["observation"]
        assert obs["type"] == kind
        assert (obs["state"] is not None) == (include_state or kind == "state")
        assert "environment" not in obs["metadata"]
        ws.send_json({"type": "state"})
        state = ws.receive_json()["data"]
        assert state["step_count"] == 1
        assert state["game_state"]["reward"] == 0.125
        assert state["environment"] == environment


@pytest.mark.parametrize("config", [
    {"obs_mode": "no-such-mode"}, {"obs_mode": []},
    {"rewards": {"no-such-reward": 1}}, {"rewards": []},
    {"rewards": {"step": 1001}}, {"rewards": {"step": "bad"}},
    {"rewards": {"step": float("nan")}},
    {"seed": -1}, {"seed": True}, {"seed": 1.5},
    {"include_state": "true"}, {"options": []},
])
def test_invalid_reset_configuration_does_not_replace_episode(config):
    with client.websocket_connect(f"{OENV}/tetris/ws") as ws:
        ws.send_json({"type": "reset", "data": {"seed": 3, "obs_mode": "state"}})
        initial = ws.receive_json()["data"]["observation"]["state"]
        ws.send_json({"type": "reset", "data": config})
        error = ws.receive_json()
        assert error["type"] == "error", error
        ws.send_json({"type": "state"})
        current = ws.receive_json()["data"]
        assert current["step_count"] == 0
        assert current["game_state"] == initial


def test_session_configuration_isolation_and_close():
    with client.websocket_connect(f"{OENV}/tetris/ws") as second:
        second.send_json({"type": "reset", "data": {"seed": 1}})
        assert second.receive_json()["data"]["observation"]["state"] is None
        with client.websocket_connect(f"{OENV}/tetris/ws") as first:
            first.send_json({"type": "reset", "data": {
                "seed": 1, "rewards": {"step": 0.25}, "include_state": True}})
            first.receive_json()
            first.send_json({"type": "step", "data": {"value": 3}})
            assert first.receive_json()["data"]["reward"] == 0.25
            # A new reset replaces configuration, rather than carrying it over.
            first.send_json({"type": "reset", "data": {"seed": 1}})
            assert first.receive_json()["data"]["observation"]["state"] is None
            first.send_json({"type": "step", "data": {"value": 3}})
            assert first.receive_json()["data"]["reward"] == -0.01
        # Closing one environment must not stop the shared package worker.
        second.send_json({"type": "step", "data": {"value": 3}})
        assert second.receive_json()["data"]["reward"] == -0.01


def test_stateless_envelope_cannot_replace_session_state():
    with client.websocket_connect(f"{OENV}/snake/ws") as ws:
        ws.send_json({"type": "reset", "data": {"seed": 4, "obs_mode": "state"}})
        initial = ws.receive_json()["data"]["observation"]["state"]
        ws.send_json({"type": "step", "data": {"value": {
            "state": _engine_new("snake", 99), "action": 1}}})
        assert ws.receive_json()["type"] == "error"
        ws.send_json({"type": "state"})
        assert ws.receive_json()["data"]["game_state"] == initial


def test_capacity_is_released_when_socket_closes(monkeypatch):
    monkeypatch.setattr(openenv_native, "MAX_WS_SESSIONS", 1)
    app = openenv_native.make_openenv_app("tetris")
    with TestClient(app) as local:
        with local.websocket_connect("/ws") as first:
            first.send_json({"type": "state"})
            assert first.receive_json()["data"]["environment"]["max_concurrent_envs"] == 1
            with local.websocket_connect("/ws") as rejected:
                error = rejected.receive_json()
                assert error["type"] == "error"
                assert error["data"]["code"] == "CAPACITY_REACHED"
        with local.websocket_connect("/ws") as replacement:
            replacement.send_json({"type": "state"})
            assert replacement.receive_json()["data"]["game_state"] is None
