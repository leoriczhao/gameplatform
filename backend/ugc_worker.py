"""UGC sandbox worker entrypoint (11 P2).

Run by ugc_runner as a restricted child process:
    python -u ugc_worker.py <game_dir>

- kernel confinement and capability stubs precede importing the user package:
  no network, no subprocess, no filesystem writes, reads only inside the
  game directory and explicitly granted runtime libraries
- protocol: one JSON object per stdin/stdout line, request/response paired
  by `id`; the first stdout line is the readiness report
- Landlock, seccomp and resource limits are applied in ugc_sandbox.install
"""
from __future__ import annotations

import builtins
import importlib.util
import json
import os
import sys
import traceback
import subprocess  # noqa: F401  (stubbed below, imported so the stub can replace it)
import socket  # noqa: F401
from pathlib import Path

ALLOWED_ROOTS: list[Path] = []


def _deny(*_a, **_kw):
    raise PermissionError("UGC 沙箱内禁止该操作")


def _install_stubs() -> None:
    """Replace dangerous capabilities with raising stubs."""
    # ---- network ----
    socket.socket = _deny
    socket.socketpair = _deny
    socket.create_connection = _deny
    # ---- subprocess / process control ----
    subprocess.Popen = _deny
    subprocess.run = _deny
    subprocess.call = _deny
    subprocess.check_call = _deny
    subprocess.check_output = _deny
    os.system = _deny
    os.popen = _deny
    os.fork = _deny
    for name in ("spawnl", "spawnle", "spawnlp", "spawnlpe", "spawnv",
                 "spawnve", "spawnvp", "spawnvpe", "execl", "execle",
                 "execlp", "execlpe", "execv", "execve", "execvp",
                 "execvpe"):
        if hasattr(os, name):
            setattr(os, name, _deny)
    # ---- filesystem writes / outside reads ----
    _orig_open = builtins.open
    roots = tuple(str(r) for r in ALLOWED_ROOTS)

    def guarded_open(file, mode="r", *args, **kwargs):
        if isinstance(file, int):
            raise PermissionError("UGC 沙箱内禁止按 fd 打开文件")
        m = set(mode)
        if m & {"w", "a", "x", "+"}:
            raise PermissionError("UGC 沙箱内禁止写文件")
        try:
            p = Path(str(file)).resolve()
        except OSError:
            p = Path(str(file))
        if not any(p == Path(r) or p.is_relative_to(Path(r)) for r in roots):
            raise PermissionError(f"只允许读取游戏目录内的文件：{file}")
        return _orig_open(file, mode, *args, **kwargs)

    builtins.open = guarded_open
    import io as _io
    _io.open = guarded_open
    # pathlib write helpers
    Path.write_text = _deny
    Path.write_bytes = _deny
    Path.touch = _deny
    Path.mkdir = _deny
    Path.unlink = _deny
    Path.rmdir = _deny
    Path.rename = _deny
    Path.replace = _deny
    # ---- dynamic native code ----
    import ctypes
    ctypes.CDLL = _deny
    ctypes.PyDLL = _deny
    ctypes.cdll.LoadLibrary = _deny
    ctypes.pydll.LoadLibrary = _deny
    ctypes.pythonapi = _deny


def _dispatch(adapter, op: str, args: dict):
    if op == "new_batch":
        results = []
        for seed in args["seeds"]:
            state = adapter.new_state(seed, args.get("options"))
            item = {"state": state}
            if args.get("obs_mode") is not None:
                item["obs"] = adapter.obs(state, args["obs_mode"])
            results.append(item)
        return results
    if op == "step_batch":
        states, actions = args["states"], args["actions"]
        if len(states) != len(actions) or not 1 <= len(states) <= 256:
            raise ValueError("batch requires 1..256 states and matching actions")
        for state, action in zip(states, actions):
            adapter.validate_state(state)
            adapter.validate_action(action, state)
        results = []
        for state, action in zip(states, actions):
            nxt = _dispatch(adapter, "step_state", {"state": state, "action": action,
                                                   "rewards": args.get("rewards")})
            item = {"state": nxt, "reward": nxt.get("reward", 0.0),
                    "done": nxt.get("done", False)}
            if "ate" in nxt:
                item["ate"] = nxt["ate"]
            if args.get("obs_mode") is not None:
                item["obs"] = adapter.obs(nxt, args["obs_mode"])
            results.append(item)
        return results
    if op == "info":
        return adapter.info()
    if op == "score_bounds":
        lo, hi = getattr(adapter, "score_bounds", (0, 1_000_000))
        return [int(lo), int(hi)]
    if op == "new_state":
        return adapter.new_state(args["seed"], args.get("options"))
    if op == "step_state":
        state, action = args["state"], args["action"]
        rewards = args.get("rewards")
        if rewards is None:
            return adapter.step_state(state, action)
        try:
            return adapter.step_state(state, action, rewards)
        except TypeError:
            return adapter.step_state(state, action)
    if op == "validate_state":
        adapter.validate_state(args["state"])
        return True
    if op == "validate_action":
        adapter.validate_action(args["action"], args["state"])
        return True
    if op == "opponent_action":
        return adapter.opponent_action(args["state"], args["config"])
    if op == "sample_action":
        return adapter.sample_action(args["state"])
    if op == "obs":
        if not hasattr(adapter, "obs"):
            return None
        return adapter.obs(args["state"], args.get("mode"))
    if op == "model_inputs":
        if not hasattr(adapter, "model_inputs"):
            raise ValueError("该游戏未声明 composite 模型协议（model_inputs）")
        try:
            return adapter.model_inputs(args["state"], args.get("owner", 0))
        except TypeError:
            return adapter.model_inputs(args["state"])
    if op == "model_decode":
        if not hasattr(adapter, "model_decode"):
            raise ValueError("该游戏未声明 composite 模型协议（model_decode）")
        try:
            return adapter.model_decode(args["outputs"], args["state"],
                                        args.get("owner", 0))
        except TypeError:
            return adapter.model_decode(args["outputs"], args["state"])
    if op == "ai_action":
        payload = args["payload"]
        if hasattr(adapter, "ai_action"):
            return adapter.ai_action(payload)
        # 未实现 ai_action 时回退到 opponent_action（ai_strategies 型游戏）
        if hasattr(adapter, "opponent_action"):
            strat = payload.get("strategy")
            cfg = {"type": "ai"}
            if strat:
                cfg["strategy"] = strat
            return {"action": adapter.opponent_action(payload["state"], cfg)}
        raise ValueError("该游戏未提供内置 AI")
    raise ValueError(f"unknown op {op!r}")


def main() -> int:
    game_dir = Path(sys.argv[1]).resolve()
    ALLOWED_ROOTS.append(game_dir)
    # -I prevents Python startup from importing code from the package/cwd.
    # Load this trusted sibling explicitly before exposing the package path.
    try:
        sandbox_spec = importlib.util.spec_from_file_location(
            "ugc_sandbox", Path(__file__).with_name("ugc_sandbox.py"))
        sandbox = importlib.util.module_from_spec(sandbox_spec)
        sandbox_spec.loader.exec_module(sandbox)
        sandbox.install(game_dir)
    except Exception as e:
        print(json.dumps({"ready": False, "error": f"UGC isolation unavailable: {e}"}), flush=True)
        return 1
    _install_stubs()
    # 多文件游戏包（12 §6 / 13 G2）：游戏目录进 sys.path 且按包加载，
    # 相对导入（from .env import …）与子模块导入均可用。
    sys.path.insert(0, str(game_dir))
    # 用户包最后才被 import：此刻 stubs 已就位
    spec = importlib.util.spec_from_file_location(
        "ugc_game", game_dir / "__init__.py",
        submodule_search_locations=[str(game_dir)])
    try:
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod   # 相对导入（from . import …）解析必需
        spec.loader.exec_module(mod)
        adapter = mod.get_adapter()
    except Exception as e:  # 加载失败：报告后退出（含完整堆栈便于定位）
        import traceback
        print(json.dumps({"ready": False,
                          "error": traceback.format_exc(limit=8)}),
              flush=True)
        return 1
    print(json.dumps({"ready": True}), flush=True)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        rid = req.get("id")
        try:
            result = _dispatch(adapter, req.get("op"), req.get("args") or {})
            resp = {"id": rid, "ok": True, "result": result}
        except Exception as e:
            resp = {"id": rid, "ok": False,
                    "error_type": type(e).__name__,
                    "error": f"{type(e).__name__}: {e}"}
        print(json.dumps(resp, default=str, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
