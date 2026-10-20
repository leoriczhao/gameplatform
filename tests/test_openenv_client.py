"""官方 OpenEnv 客户端端到端（docs/design/15 v2）。

真实 uvicorn + 官方 GenericEnvClient（openenv 包自带）：客户端无需任何
platform 特定代码，直接连 ws://…/api/openenv/{game}/ws 完成 reset/step/state
循环 —— 证明平台就是「完整的 OpenEnv 环境」。
"""
import json
import os
import sys
from pathlib import Path

import requests

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

from live_server import live_server  # noqa: E402
from openenv.core import GenericEnvClient  # noqa: E402


def _test_client_against(base: str) -> None:
    """官方 GenericEnvClient（同步模式）打完一整局 snake。"""
    with GenericEnvClient(base_url=f"{base}/api/openenv/snake").sync() as env:
        result = env.reset(seed=5)
        obs = result.observation
        assert obs["type"] == "tensor"
        assert env.state()["step_count"] == 0
        for a in (1, 1, 0, 2, 1):
            result = env.step({"value": a})
            assert result.observation["type"] == "tensor"
        st = env.state()
        assert st["step_count"] == 5
        assert st["episode_id"] is None  # reset 未传 episode_id
        # Compare to the package engine, not a second public environment API.
        from pkgload import load_game_package
        adapter = load_game_package("snake").get_adapter()
        expected = adapter.new_state(5)
        for action in (1, 1, 0, 2, 1):
            expected = adapter.step_state(expected, action)
        assert st["game_state"] == json.loads(json.dumps(expected))
        assert st["environment"]["version"]
        assert result.observation["metadata"]["tick"] == expected["tick"]
        assert result.observation["metadata"]["score"] == expected["score"]
        for operation in ("info", "new_batch", "step"):
            response = requests.request("GET" if operation == "info" else "POST",
                                        f"{base}/api/snake/env/{operation}", timeout=10)
            assert response.status_code == 404



def test_official_client_end_to_end():
    with live_server() as base:
        _test_client_against(base)


def test_official_http_wire_live():
    """HTTP 面在真实服务器上的形状抽查（官方协议）。"""
    with live_server() as base:
        s = requests.get(f"{base}/api/openenv/tetris/schema", timeout=10).json()
        assert set(s) == {"action", "observation", "state"}
        r = requests.post(f"{base}/api/openenv/tetris/reset",
                          json={"seed": 7}, timeout=10)
        assert r.status_code == 200
        assert r.json()["observation"]["shape"] == [2, 20, 10]
        tas = requests.get(f"{base}/api/openenv/tetris/tetris/splits", timeout=10).json()
        assert tas == [{"name": "default", "type": "validation"}]
