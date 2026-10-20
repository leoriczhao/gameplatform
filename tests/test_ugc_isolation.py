"""Exercise real kernel boundaries using the same worker as uploads/play."""
import os
from pathlib import Path
import shutil
import sys
import time

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import ugc_runner
import ugc_static


@pytest.mark.parametrize("operation", ["read", "write", "chmod", "socket", "spawn"])
def test_indirect_capabilities_denied(tmp_path, operation):
    outside = tmp_path / "platform-data"
    outside.write_text("private-marker")
    outside.chmod(0o600)
    package = tmp_path / "game"
    package.mkdir()
    expressions = {
        "read": f"random._os.open({str(outside)!r}, random._os.O_RDONLY)",
        "write": f"random._os.open({str(outside)!r}, random._os.O_WRONLY | random._os.O_TRUNC)",
        "chmod": f"random._os.chmod({str(outside)!r}, 0)",
        "socket": "random._os.sys.modules['_socket'].socket()",
        "spawn": "random._os.posix_spawn('/usr/bin/true', ['true'], {})",
    }
    (package / "__init__.py").write_text(
        "import random\nclass Game:\n    def info(self):\n        "
        + expressions[operation] + "\n        return {}\ndef get_adapter(): return Game()\n")
    assert ugc_static.scan_dir(package)["ok"]
    worker = ugc_runner.GameWorker("isolation-test", package)
    try:
        with pytest.raises(ugc_runner.WorkerError, match="PermissionError"):
            worker.request("info")
    finally:
        worker.stop()
    assert outside.read_text() == "private-marker"
    assert outside.stat().st_mode & 0o777 == 0o600


def test_package_reads_work_and_environment_is_clean(tmp_path, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "private-env-marker")
    monkeypatch.setenv("OPENBLAS_NUM_THREADS", "32")
    (tmp_path / "asset.txt").write_text("game-asset")
    (tmp_path / "__init__.py").write_text('''import random
import numpy as np
class Game:
    def info(self):
        return {"asset": open("asset.txt").read(),
                "sum": int(np.arange(4).sum()),
                "secret": random._os.environ.get("ADMIN_PASSWORD")}
def get_adapter(): return Game()
''')
    worker = ugc_runner.GameWorker("legitimate", tmp_path)
    try:
        assert worker.request("info") == {"asset": "game-asset", "sum": 6, "secret": None}
    finally:
        worker.stop()


def test_unavailable_isolation_never_imports_game(tmp_path, monkeypatch):
    trusted = tmp_path / "trusted"
    trusted.mkdir()
    shutil.copy(ugc_runner.WORKER_PATH, trusted / "ugc_worker.py")
    (trusted / "ugc_sandbox.py").write_text(
        "def install(game_dir): raise RuntimeError('isolation unavailable for test')\n")
    game = tmp_path / "game"
    game.mkdir()
    marker = tmp_path / "must-not-exist"
    (game / "__init__.py").write_text(f"open({str(marker)!r}, 'w').write('ran')\n")
    monkeypatch.setattr(ugc_runner, "WORKER_PATH", trusted / "ugc_worker.py")
    with pytest.raises(ugc_runner.GameLoadError, match="isolation unavailable for test"):
        ugc_runner.GameWorker("fail-closed", game)
    assert not marker.exists()


def test_descriptor_control_denied_even_without_static_scanner(tmp_path):
    # Test the kernel layer directly; descriptor ownership must not be mutable.
    (tmp_path / "__init__.py").write_text('''import fcntl
import os
class Game:
    def info(self):
        fcntl.fcntl(0, fcntl.F_SETOWN, os.getpid())
        return {}
def get_adapter(): return Game()
''')
    worker = ugc_runner.GameWorker("descriptor-control", tmp_path)
    try:
        with pytest.raises(ugc_runner.WorkerError, match="PermissionError"):
            worker.request("info")
    finally:
        worker.stop()


def test_smoke_worker_is_reaped(tmp_path, monkeypatch):
    import ugc
    workers = []
    original = ugc_runner.GameWorker
    def track(*args, **kwargs):
        worker = original(*args, **kwargs)
        workers.append((worker, worker._proc))
        return worker
    monkeypatch.setattr(ugc_runner, "GameWorker", track)
    (tmp_path / "__init__.py").write_text('''class Game:
    score_bounds = (0, 1)
    def info(self): return {}
    def new_state(self, seed, options=None): return {"done": True}
    def validate_state(self, state): pass
def get_adapter(): return Game()
''')
    result = ugc._smoke("smoke-reaping", tmp_path, {})
    assert result["ok"], result
    assert workers and all(w._stopped and proc.poll() is not None for w, proc in workers)


def test_malformed_worker_output_does_not_break_response_reader(tmp_path):
    (tmp_path / "__init__.py").write_text('''import random
class Game:
    def info(self):
        random._os.write(1, b'\\xff\\n{"id":[]}\\n')
        return {"alive": True}
def get_adapter(): return Game()
''')
    worker = ugc_runner.GameWorker("malformed-output", tmp_path)
    try:
        assert worker.request("info") == {"alive": True}
    finally:
        worker.stop()


def test_oversized_worker_response_is_killed(tmp_path):
    (tmp_path / "__init__.py").write_text(f'''class Game:
    def info(self): return "x" * {ugc_runner.MAX_MESSAGE_BYTES + 1}
def get_adapter(): return Game()
''')
    worker = ugc_runner.GameWorker("oversized-output", tmp_path)
    proc = worker._proc
    try:
        with pytest.raises(ugc_runner.WorkerError):
            worker.request("info", timeout=2)
        assert proc.poll() is not None
    finally:
        worker.stop()


def test_worker_not_reading_input_cannot_block_parent(tmp_path):
    (tmp_path / "__init__.py").write_text('''import time
def get_adapter():
    print('{"ready":true}', flush=True)
    while True: time.sleep(1)
''')
    worker = ugc_runner.GameWorker("blocked-input", tmp_path)
    proc = worker._proc
    start = time.monotonic()
    try:
        with pytest.raises(ugc_runner.WorkerTimeout, match="write timed out"):
            worker.request("info", padding="x" * 1_000_000)
        assert time.monotonic() - start < 3
        assert proc.poll() is not None
    finally:
        worker.stop()
