"""UGC 游戏接入 OpenEnv 官方面的集成测试（docs/design/15 v2）。

验证链路：UGC 上传 -> 审核发布 -> 注册表注册 -> 自动挂载 /api/openenv/{slug}/*
（官方 openenv 栈；无需作者做任何 OpenEnv 特定工作，鸭子类型 EnvAdapter 即满足）
+ 无服务端 obs_modes 时的观测回退 + 与内部沙箱引擎逐位一致。
"""
import io
import os
import sys
import tempfile
import textwrap
import zipfile
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

_tmp = tempfile.TemporaryDirectory()
os.environ["SCORES_DB"] = str(Path(_tmp.name) / "scores.db")
os.environ["MODELS_DIR"] = str(Path(_tmp.name) / "models")

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
import registry  # noqa: E402

client = TestClient(main.app)

OENV = "/api/openenv"


def _engine_new(game: str, seed: int) -> dict:
    return registry.GAMES[game].new_state(seed)


def _engine_step(game: str, state: dict, action) -> dict:
    adapter = registry.GAMES[game]
    nxt = adapter.step_state(state, action, adapter.info().get("default_rewards") or {})
    return {"state": nxt, "reward": nxt.get("reward", 0.0), "done": nxt.get("done", False)}


# ---------------------------------------------------------------- UGC fixture


def _ugc_upload_and_publish(slug: str, admin: dict) -> None:
    """上传 -> 提交审核 -> 管理员通过（等价 test_ugc_api 的发布路径）。"""
    yaml = (
        f"slug: {slug}\n"
        "title: UGC计数器\n"
        "description: 测试用计数器\n"
        "version: 1.0.0\n"
        "board:\n"
        "  width: 4\n"
        "  height: 4\n"
        "  palette:\n"
        '    empty: { glyph: "·" }\n'
        '    full:  { glyph: "■" }\n'
    )
    code = textwrap.dedent("""
        class Counter:
            score_bounds = (0, 100)
            def info(self):
                return {"grid": [4, 4], "action_space": "0-1"}
            def new_state(self, seed, options=None):
                return {"tick": 0, "done": False, "winner": None, "cause": None,
                        "n": 0, "board": [["empty"] * 4 for _ in range(4)]}
            def validate_state(self, state):
                if state["board"][0][0] not in ("empty", "full"):
                    raise ValueError("bad cell")
            def validate_action(self, action, state):
                if not isinstance(action, int):
                    raise ValueError("int required")
            def step_state(self, state, action):
                if state.get("done"):
                    return state
                s = dict(state, n=state["n"] + 1, tick=state["tick"] + 1)
                s["board"] = [row[:] for row in state["board"]]
                s["board"][0][0] = "full" if s["n"] >= 10 else "empty"
                if s["n"] >= 10:
                    s.update(done=True, winner=0, cause="done")
                return s
            def sample_action(self, state):
                return 1
        def get_adapter():
            return Counter()
    """)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("game.yaml", yaml)
        zf.writestr("__init__.py", code)
        zf.writestr("README.md", "# 玩法\n")

    # 用户名只允许字母/数字/下划线（slug 允许连字符）
    user_name = slug.replace("-", "_")
    r = client.post("/api/v1/auth/register",
                    json={"username": user_name, "password": "password123"})
    assert r.status_code == 200, r.text
    u = r.json()
    h = {"Authorization": f"Bearer {u['token']}"}
    r = client.post("/api/v1/ugc/games",
                    files={"file": (slug + ".zip", buf.getvalue(), "application/zip")},
                    data={"changelog": "init"}, headers=h)
    assert r.status_code == 200, r.text
    gid = r.json()["game"]["id"]
    assert client.post(f"/api/v1/ugc/games/{gid}/submit", headers=h).status_code == 200
    ah = {"Authorization": "Bearer " + admin["token"]}
    r = client.post(f"/api/v1/admin/ugc/{gid}/approve", headers=ah)
    assert r.status_code == 200, r.text


@pytest.fixture
def ugc_admin(monkeypatch):
    monkeypatch.setenv("ADMIN_USERNAME", "oeadmin1")
    monkeypatch.setenv("ADMIN_PASSWORD", "adminsecret1")
    import admin as admin_store  # noqa: E402
    admin_store.bootstrap_admin()
    r = client.post("/api/v1/auth/login",
                    json={"username": "oeadmin1", "password": "adminsecret1"})
    assert r.status_code == 200, r.text
    return r.json()


import itertools as _itertools

# 单一计数器实例（每次 next 递增），生成唯一 slug
_SLUG_COUNTER = _itertools.count()


@pytest.fixture
def ugc_counter(ugc_admin):
    # function-scoped：每次用例发布一个唯一 slug（同名冲突与注册表污染都避免：
    # teardown 时 unregister，防止同进程后续 test_registry 等断言注册表集合失败）
    slug = f"counter-oe{next(_SLUG_COUNTER)}"
    _ugc_upload_and_publish(slug, ugc_admin)
    assert slug in registry.GAMES
    yield slug
    registry.unregister(slug)


# ------------------------------------------------------------------ 用例


def test_ugc_game_gets_openenv_listing(ugc_counter):
    """发布后自动出现在 OpenEnv 环境目录（不需要任何 OpenEnv 特定代码）。"""
    r = client.get(f"{OENV}/list_environments")
    assert r.status_code == 200
    assert ugc_counter in r.json()


def test_ugc_schema_metadata(ugc_counter):
    r = client.get(f"{OENV}/{ugc_counter}/schema")
    assert r.status_code == 200, r.text
    assert r.json()["action"]["required"] == ["value"]
    m = client.get(f"{OENV}/{ugc_counter}/metadata").json()
    assert m["version"] == "1.0.0"
    assert m["author"]  # UGC 作者昵称（非「官方」）


def test_ugc_reset_no_obs_mode_returns_state_observation(ugc_counter):
    """UGC 游戏若未声明服务端 obs_modes，观测回退为 state 透传。"""
    r = client.post(f"{OENV}/{ugc_counter}/reset", json={"seed": 2})
    assert r.status_code == 200, r.text
    obs = r.json()["observation"]
    assert obs["type"] == "state"
    assert obs["state"]["n"] == 0


def test_ugc_ws_step_parity_with_engine(ugc_counter):
    """Every OpenEnv transition agrees with the published sandbox engine."""
    state = _engine_new(ugc_counter, 3)
    with client.websocket_connect(f"{OENV}/{ugc_counter}/ws") as ws:
        ws.send_json({"type": "reset", "data": {"seed": 3}})
        assert ws.receive_json()["data"]["observation"]["state"] == state
        for _ in range(12):
            ws.send_json({"type": "step", "data": {"value": 1}})
            oe = ws.receive_json()["data"]
            expected = _engine_step(ugc_counter, state, 1)
            assert oe["reward"] == expected["reward"]
            assert oe["done"] == expected["done"]
            assert oe["observation"]["state"] == expected["state"]
            state = expected["state"]
            if expected["done"]:
                break
    assert state["done"] is True


def test_ugc_ws_session(ugc_counter):
    """UGC 游戏走 WS 会话（OpenEnv client 生产路径）完整可玩。"""
    with client.websocket_connect(f"{OENV}/{ugc_counter}/ws") as ws:
        ws.send_json({"type": "reset", "data": {"seed": 1}})
        d = ws.receive_json()["data"]
        assert d["observation"]["type"] == "state"
        done, steps = d["done"], 0
        while not done and steps < 10:
            ws.send_json({"type": "step", "data": {"value": 1}})
            d = ws.receive_json()["data"]
            done, steps = d["done"], steps + 1
        assert done is True  # n>=10 终止
        ws.send_json({"type": "state"})
        st = ws.receive_json()
        assert st["type"] == "state"
        assert st["data"]["step_count"] >= 10
        ws.send_json({"type": "close"})
