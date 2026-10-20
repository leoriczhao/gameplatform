"""Fresh, loopback-only real HTTP server for integration/acceptance tests."""
from contextlib import contextmanager
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time

import requests

ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def live_server(*, admin=True, data_dir=None):
    with tempfile.TemporaryDirectory(prefix="gp-live-test-") as tmp:
        data = Path(data_dir or tmp)
        data.mkdir(parents=True, exist_ok=True)
        env = {**os.environ, "SCORES_DB": str(data / "scores.db"),
               "MODELS_DIR": str(data / "models"),
               "ADMIN_USERNAME": "smokeadmin" if admin else "",
               "ADMIN_PASSWORD": "smoke-local-password" if admin else "",
               "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1"}
        env.pop("PYTHONPATH", None)
        with socket.socket() as sock, tempfile.TemporaryFile(mode="w+") as log:
            sock.bind(("127.0.0.1", 0))
            base = f"http://127.0.0.1:{sock.getsockname()[1]}"
            code = ("import socket,uvicorn; "
                    f"s=socket.socket(fileno={sock.fileno()}); "
                    "uvicorn.Server(uvicorn.Config('main:app',log_level='warning')).run(sockets=[s])")
            proc = subprocess.Popen([sys.executable, "-c", code],
                                    cwd=ROOT / "backend", env=env,
                                    pass_fds=(sock.fileno(),), stdout=log, stderr=log)
            try:
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline and proc.poll() is None:
                    try:
                        if requests.get(base + "/api/health", timeout=.3).status_code == 200:
                            break
                    except requests.RequestException:
                        pass
                    time.sleep(.05)
                else:
                    log.seek(0)
                    raise AssertionError(f"fresh server did not start: {log.read()}")
                yield base
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
