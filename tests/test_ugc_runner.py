"""UGC sandbox runner tests (11 P2): roundtrip, determinism, deny stubs,
timeout/memory enforcement, crash restart + 熔断, idle reaping, proxy face,"
registry sources."""
import io
import json
import sys
import tempfile
import time
import zipfile
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

import ugc_pack  # noqa: E402
import ugc_proxy  # noqa: E402
import ugc_runner  # noqa: E402
import registry  # noqa: E402

GOOD_YAML = """slug: counter
title: 计数器
description: 测试用计数器
version: 1.0.0
board:
  width: 4
  height: 4
  palette:
    empty: { glyph: "·" }
    full:  { glyph: "■" }
"""

COUNTER_CODE = '''
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
    def opponent_action(self, state, config):
        return 0
    def sample_action(self, state):
        return 1
def get_adapter():
    return Counter()
'''


def _make_game(game_id, code, yaml=GOOD_YAML, extra=None) -> tuple[Path, dict]:
    """zip -> extract 到临时目录；返回 (解包目录, meta)。"""
    files = {"game.yaml": yaml, "__init__.py": code}
    if extra:
        files.update(extra)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    tmp = tempfile.mkdtemp(prefix=f"ugc-{game_id}-")
    dest = Path(tmp) / game_id
    rep = ugc_pack.extract_package(buf.getvalue(), dest)
    return dest, rep["meta"]


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    ugc_runner.stop_all()


def _new_worker(game_id, code, on_unhealthy=None, step_timeout=None):
    game_dir, meta = _make_game(game_id, code)
    kwargs = {"on_unhealthy": on_unhealthy}
    if step_timeout is not None:
        kwargs["step_timeout"] = step_timeout
    w = ugc_runner.GameWorker(game_id, game_dir, **kwargs)
    return w, meta


def test_worker_roundtrip_and_determinism():
    w1, _ = _new_worker("rt1", COUNTER_CODE)
    w2, _ = _new_worker("rt2", COUNTER_CODE)
    info = w1.request("info")
    assert info["grid"] == [4, 4]
    s1 = w1.request("new_state", seed=42)
    s2 = w2.request("new_state", seed=42)
    assert s1 == s2, "同 seed 必须同轨迹"
    assert w1.request("validate_state", state=s1) is True
    assert w1.request("validate_action", action=1, state=s1) is True
    for _ in range(10):
        s1 = w1.request("step_state", state=s1, action=1)
    assert s1["done"] is True and s1["winner"] == 0
    # done 后不再推进
    s1b = w1.request("step_state", state=s1, action=1)
    assert s1b["n"] == s1["n"]
    # opponent_action / sample_action 透传
    assert w1.request("opponent_action", state=s1,
                      config={"type": "ai", "strategy": "x"}) == 0
    assert w1.request("sample_action", state=s1) == 1
    assert w1.request("score_bounds") == [0, 100]


def test_proxy_adapter_face():
    game_dir, meta = _make_game("proxy1", COUNTER_CODE)
    p = ugc_proxy.ProxyAdapter("proxy1", game_dir, meta)
    assert p.game_id == "proxy1" and p.name == "计数器"
    assert p.pvp_enabled is False
    assert p.score_bounds == (0, 100)
    info = p.info()
    assert info["grid"] == [4, 4]
    s = p.new_state(7)
    p.validate_state(s)
    p.validate_action(1, s)
    s2 = p.step_state(s, 1, rewards=None)
    assert s2["tick"] == 1
    assert p.opponent_action(s, {"type": "ai", "strategy": "x"}) == 0
    assert p.sample_action(s) == 1
    # 未声明 ai_strategies → 不挂 /ai/action（11 P5）
    assert p.ai_request_model is None
    p2 = ugc_proxy.ProxyAdapter("proxy1", game_dir, {**meta, "ai_strategies": ["greedy"]})
    assert ugc_proxy.UGCAIRequest is p2.ai_request_model


def test_worker_load_error():
    with pytest.raises(ugc_runner.GameLoadError, match="boom"):
        _new_worker("badload", "raise RuntimeError('boom')\n")


def test_worker_network_denied():
    code = '''
def get_adapter():
    raise RuntimeError("unused")
'''
    net_code = '''
import socket
def get_adapter():
    socket.socket()
    raise RuntimeError("unused")
'''
    # import 时触发 socket 桩 → 加载失败
    with pytest.raises(ugc_runner.GameLoadError):
        _new_worker("badnet", net_code)


def test_worker_file_write_denied():
    write_code = '''
class G:
    def new_state(self, seed, options=None):
        open("x.txt", "w").write("evil")
        return {}
    def step_state(self, s, a): return s
    def validate_state(self, s): pass
    def validate_action(self, a, s): pass
def get_adapter():
    return G()
'''
    w, _ = _new_worker("badwrite", write_code)
    with pytest.raises(ugc_runner.WorkerError, match="禁止写文件"):
        w.request("new_state", seed=1)


def test_worker_timeout_fuse(monkeypatch):
    monkeypatch.setattr(ugc_runner, "RESTART_BACKOFF", (0.01, 0.02))
    loop_code = '''
class G:
    def new_state(self, seed, options=None):
        while True:
            pass
    def step_state(self, s, a): return s
    def validate_state(self, s): pass
    def validate_action(self, a, s): pass
def get_adapter():
    return G()
'''
    fired = []
    w, _ = _new_worker("badloop", loop_code,
                       on_unhealthy=lambda gid: fired.append(gid),
                       step_timeout=0.2)
    t0 = time.time()
    with pytest.raises(ugc_runner.WorkerTimeout):
        w.request("new_state", seed=1)
    assert time.time() - t0 < 3, "超时必须快速强杀"
    with pytest.raises(ugc_runner.WorkerTimeout):
        w.request("new_state", seed=1)
    with pytest.raises(ugc_runner.WorkerTimeout):
        w.request("new_state", seed=1)
    assert fired == ["badloop"], "连续 3 次失败应熔断"
    with pytest.raises(ugc_runner.WorkerError, match="熔断"):
        w.request("new_state", seed=1)


def test_worker_memory_limit():
    mem_code = '''
class G:
    def new_state(self, seed, options=None):
        x = [0] * 300_000_000   # ~2.4GB，撞 RLIMIT_AS
        return {}
    def step_state(self, s, a): return s
    def validate_state(self, s): pass
    def validate_action(self, a, s): pass
def get_adapter():
    return G()
'''
    w, _ = _new_worker("badmem", mem_code)
    with pytest.raises(ugc_runner.WorkerError, match="MemoryError"):
        w.request("new_state", seed=1)


def test_worker_crash_restart_and_fuse(monkeypatch):
    monkeypatch.setattr(ugc_runner, "RESTART_BACKOFF", (0.01, 0.02))
    monkeypatch.setattr(ugc_runner, "MAX_FAILURES", 2)
    crash_code = '''
import os
class G:
    def new_state(self, seed, options=None):
        os._exit(1)
    def step_state(self, s, a): return s
    def validate_state(self, s): pass
    def validate_action(self, a, s): pass
def get_adapter():
    return G()
'''
    fired = []
    w, _ = _new_worker("badcrash", crash_code,
                       on_unhealthy=lambda gid: fired.append(gid))
    with pytest.raises(ugc_runner.WorkerError, match="崩溃"):
        w.request("new_state", seed=1)
    with pytest.raises(ugc_runner.WorkerError, match="崩溃"):
        w.request("new_state", seed=1)
    assert fired == ["badcrash"]
    # 崩溃进程未拖垮父进程：父进程一切正常
    assert ugc_runner.get_worker.__name__ == "get_worker"


def test_idle_cleanup_reaps_workers():
    game_dir, meta = _make_game("idle1", COUNTER_CODE)
    w1 = ugc_runner.get_worker("idle1", game_dir)
    w1.request("new_state", seed=1)
    # 未到超时：不回收
    assert ugc_runner.idle_cleanup(now=time.time() + 100) == 0
    assert ugc_runner.get_worker("idle1", game_dir) is w1
    # 超过 IDLE_TIMEOUT：回收，下次拿到新 worker
    assert ugc_runner.idle_cleanup(now=time.time() + ugc_runner.IDLE_TIMEOUT + 1) == 1
    w2 = ugc_runner.get_worker("idle1", game_dir)
    assert w2 is not w1
    w2.request("new_state", seed=1)


def test_registry_sources_and_unregister():
    class FakeAdapter:
        game_id = "fake-game"
    registry.unregister("fake-game")
    registry.register(FakeAdapter(), source="ugc")
    assert "fake-game" in registry.GAMES
    with pytest.raises(ValueError, match="already registered"):
        registry.register(FakeAdapter(), source="ugc")
    registry.unregister("fake-game")
    assert "fake-game" not in registry.GAMES
    registry.unregister("fake-game")   # 幂等
