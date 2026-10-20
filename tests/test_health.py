"""Health endpoint extension test (v1.0-e)."""
import os
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

_tmp = tempfile.TemporaryDirectory()
os.environ["SCORES_DB"] = str(Path(_tmp.name) / "scores.db")
os.environ["MODELS_DIR"] = str(Path(_tmp.name) / "models")

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402

client = TestClient(main.app)


def test_health_has_ops_metrics():
    r = client.get("/api/health")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["status"] == "ok"
    assert isinstance(d["active_sessions"], int)
    assert isinstance(d["db_size_bytes"], int)
    assert set(d["games"].keys()) == {"microrts", "snake", "tetris"}
