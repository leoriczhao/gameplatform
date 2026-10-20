"""UGC sandbox runner (11 P2): one restricted worker process per game.

- lazy start; long-lived worker; newline-JSON over stdio
- per-request timeout (default 200ms) -> kill the process group
- mandatory Landlock/seccomp + rlimits in the isolated Python worker
- crash/timeout restarts with backoff; MAX_FAILURES consecutive failures
  mark the game unhealthy and fire the on_unhealthy callback (熔断)
- idle workers are reaped by idle_cleanup() (10 minutes default)
"""
from __future__ import annotations

import json
import os
import select
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

WORKER_PATH = Path(__file__).with_name("ugc_worker.py")
STEP_TIMEOUT = 0.2          # 每请求默认超时（秒）
START_TIMEOUT = 15.0        # worker 启动（含 import 用户包）上限
IDLE_TIMEOUT = 600.0        # 空闲回收（秒）
MAX_FAILURES = 3            # 连续失败熔断阈值
RESTART_BACKOFF = (0.5, 1.0, 2.0)   # 重启退避（秒）
MAX_MESSAGE_BYTES = 16 * 1024 * 1024


class WorkerError(RuntimeError):
    """Worker returned an error / crashed / is unhealthy."""


class WorkerInputError(WorkerError, ValueError):
    """The package rejected an input; preserve HTTP validation semantics."""


class GameLoadError(WorkerError):
    """The user package failed to import."""


class WorkerTimeout(WorkerError):
    """A request exceeded the step timeout; the worker was killed."""


class GameWorker:
    """One sandboxed game process + its request bookkeeping."""

    def __init__(self, game_id: str, game_dir: Path,
                 on_unhealthy=None, step_timeout: float = STEP_TIMEOUT):
        self.game_id = game_id
        self.game_dir = Path(game_dir).resolve()
        self.on_unhealthy = on_unhealthy
        self.step_timeout = step_timeout
        self.last_used = time.time()
        self._lock = threading.Lock()
        self._next_id = 1
        self._pending: dict[int, tuple[threading.Event, dict]] = {}
        self._proc: subprocess.Popen | None = None
        self._ready = threading.Event()
        self._ready_error: str | None = None
        self._failures = 0
        self._unhealthy = False
        self._stopped = False
        self._reader = None
        self._start()

    # ------------------------------------------------------------ lifecycle
    def _start(self) -> None:
        self._ready.clear()
        self._ready_error = None
        self._proc = subprocess.Popen(
            [sys.executable, "-I", "-u", str(WORKER_PATH), str(self.game_dir)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, bufsize=65536,
            start_new_session=True, close_fds=True,
            env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8",
                 "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1"},
            cwd=str(self.game_dir))   # v2：包内相对路径读资源（12 §3）
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        if not self._ready.wait(START_TIMEOUT):
            self._kill()
            raise GameLoadError(f"游戏 {self.game_id} 加载超时（{START_TIMEOUT}s）")
        if self._ready_error:
            self._kill()
            raise GameLoadError(self._ready_error)
        os.set_blocking(self._proc.stdin.fileno(), False)

    def _read_loop(self) -> None:
        proc = self._proc
        assert proc and proc.stdout
        while True:
            raw = proc.stdout.readline(MAX_MESSAGE_BYTES + 1)
            if not raw:
                break
            if len(raw) > MAX_MESSAGE_BYTES:
                self._ready_error = "worker response exceeds 16 MiB limit"
                self._kill()
                break
            raw = raw.strip()
            if not raw:
                continue
            try:
                msg = json.loads(raw)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            if not isinstance(msg, dict):
                continue
            if "ready" in msg and not self._ready.is_set():
                if msg["ready"]:
                    self._ready.set()
                else:
                    self._ready_error = msg.get("error", "加载失败")
                    self._ready.set()
                continue
            rid = msg.get("id")
            if not isinstance(rid, int):
                continue
            pair = self._pending.get(rid)
            if pair:
                pair[1]["resp"] = msg
                pair[0].set()
        if not self._ready.is_set():
            self._ready_error = "worker exited before sandbox initialization completed"
            self._ready.set()
        # EOF / crash：唤醒所有等待者
        for evt, slot in list(self._pending.values()):
            slot["resp"] = None
            evt.set()
        self._pending.clear()

    def _kill(self) -> None:
        proc = self._proc
        self._proc = None
        if proc is None:
            return
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            proc.kill()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        if self._reader is not None and self._reader is not threading.current_thread():
            self._reader.join(timeout=1)
        for pipe in (proc.stdin, proc.stdout):
            if pipe is not None:
                pipe.close()

    def stop(self) -> None:
        self._stopped = True
        self._kill()

    def _fail(self, exc: WorkerError) -> None:
        self._kill()
        self._failures += 1
        if self._failures >= MAX_FAILURES and not self._unhealthy:
            self._unhealthy = True
            if self.on_unhealthy:
                try:
                    self.on_unhealthy(self.game_id)
                except Exception:
                    pass
        raise exc

    def _ensure_alive(self) -> None:
        """Lazy restart after a crash/timeout, with backoff."""
        if self._proc is not None and self._proc.poll() is None:
            return
        if self._failures:
            backoff = RESTART_BACKOFF[min(self._failures, len(RESTART_BACKOFF)) - 1]
            time.sleep(backoff)
        self._start()

    # -------------------------------------------------------------- request
    def request(self, op: str, timeout: float | None = None, **args):
        if self._unhealthy:
            raise WorkerError(f"游戏 {self.game_id} 已熔断（连续 {MAX_FAILURES} 次失败）")
        with self._lock:
            if self._stopped:
                raise WorkerError("worker 已停止")
            self._ensure_alive()
            rid = self._next_id
            self._next_id += 1
            evt, slot = threading.Event(), {}
            self._pending[rid] = (evt, slot)
            budget = timeout if timeout is not None else self.step_timeout
            deadline = time.monotonic() + budget
            try:
                message = (json.dumps({"id": rid, "op": op, "args": args},
                                      ensure_ascii=False) + "\n").encode("utf-8")
                if len(message) > MAX_MESSAGE_BYTES:
                    raise WorkerInputError("worker request exceeds 16 MiB limit")
                pending = memoryview(message)
                proc = self._proc
                if proc is None or proc.poll() is not None:
                    self._fail(WorkerError("worker exited before request write"))
                fd = proc.stdin.fileno()
                while pending:
                    left = max(0., deadline - time.monotonic())
                    if not select.select([], [fd], [], left)[1]:
                        self._fail(WorkerTimeout(f"游戏 {self.game_id} request write timed out"))
                    try:
                        pending = pending[os.write(fd, pending):]
                    except BlockingIOError:
                        continue
            except (BrokenPipeError, OSError) as e:
                self._pending.pop(rid, None)
                self._fail(WorkerError(f"worker 写入失败：{e}"))
            except Exception:
                self._pending.pop(rid, None)
                raise
            if not evt.wait(max(0., deadline - time.monotonic())):
                self._pending.pop(rid, None)
                self._fail(WorkerTimeout(
                    f"游戏 {self.game_id} step 超时（{budget}s），已强杀"))
            self._pending.pop(rid, None)
            resp = slot.get("resp")
            if resp is None:
                self._fail(WorkerError(f"worker 崩溃（{op}）"))
            if not resp.get("ok"):
                if resp.get("error_type") in ("ValueError", "KeyError", "TypeError"):
                    raise WorkerInputError(resp.get("error", "invalid input"))
                raise WorkerError(resp.get("error", "unknown"))
            self._failures = 0
            self.last_used = time.time()
            return resp.get("result")


# --------------------------------------------------------------- pool/registry

_WORKERS: dict[tuple[str, str], GameWorker] = {}
_WLOCK = threading.Lock()


def get_worker(game_id: str, game_dir: Path, on_unhealthy=None,
               step_timeout: float = STEP_TIMEOUT) -> GameWorker:
    key = (game_id, str(Path(game_dir).resolve()))
    with _WLOCK:
        w = _WORKERS.get(key)
        if w is not None and not w._stopped:
            return w
        w = GameWorker(game_id, game_dir, on_unhealthy=on_unhealthy,
                       step_timeout=step_timeout)
        _WORKERS[key] = w
        return w


def drop_worker(game_id: str) -> None:
    """Stop and forget one game's worker (version swap / unpublish)."""
    with _WLOCK:
        workers = [_WORKERS.pop(key) for key in list(_WORKERS) if key[0] == game_id]
    for worker in workers:
        worker.stop()


def idle_cleanup(now: float | None = None) -> int:
    """Stop workers idle longer than IDLE_TIMEOUT; returns count stopped."""
    now = time.time() if now is None else now
    with _WLOCK:
        stale = [gid for gid, w in _WORKERS.items()
                 if not w._stopped and now - w.last_used > IDLE_TIMEOUT]
        for gid in stale:
            _WORKERS[gid].stop()
            del _WORKERS[gid]
    return len(stale)


def stop_all() -> None:
    with _WLOCK:
        for w in _WORKERS.values():
            w.stop()
        _WORKERS.clear()
