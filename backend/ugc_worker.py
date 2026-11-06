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

# Trusted kernel first: after confinement its files are no longer readable.
from gamekernel.calls import GameCalls  # noqa: E402
from gamekernel.loader import load_package  # noqa: E402

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
    # 用户包最后才被 import：此刻 stubs 已就位（加载规则见 gamekernel.loader）
    try:
        calls = GameCalls(load_package(game_dir))
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
            result = calls.dispatch(req.get("op"), req.get("args") or {})
            resp = {"id": rid, "ok": True, "result": result}
        except Exception as e:
            resp = {"id": rid, "ok": False,
                    "error_type": type(e).__name__,
                    "error": f"{type(e).__name__}: {e}"}
        print(json.dumps(resp, default=str, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
