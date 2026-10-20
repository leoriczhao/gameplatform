"""Official seed packages (13 G2): packaged-games/{snake,tetris,microrts} go
through the exact upload pipeline (validate → scan → extract → smoke in the
sandbox) and publish directly. No registry swap here — that's G3's seed loader."""
import io
import os
import sys
import tempfile
import zipfile
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent / "backend"
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))

_tmp = tempfile.TemporaryDirectory()
os.environ["SCORES_DB"] = str(Path(_tmp.name) / "scores.db")
os.environ["MODELS_DIR"] = str(Path(_tmp.name) / "models")

from fastapi.testclient import TestClient  # noqa: E402

import admin as admin_store  # noqa: E402
import main  # noqa: E402
import ugc  # noqa: E402

client = TestClient(main.app)


def _zip_package(dirpath: Path) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for p in sorted(dirpath.rglob("*")):
            if p.is_dir() or "__pycache__" in p.parts:
                continue
            zf.writestr(p.relative_to(dirpath).as_posix(), p.read_bytes())
    return buf.getvalue()


@pytest.fixture
def admin_id(monkeypatch):
    monkeypatch.setenv("ADMIN_USERNAME", "seedadmin")
    monkeypatch.setenv("ADMIN_PASSWORD", "adminsecret1")
    admin_store.bootstrap_admin()
    r = client.post("/api/v1/auth/login",
                    json={"username": "seedadmin", "password": "adminsecret1"})
    return r.json()["user"]["id"]


def test_seed_all_official_packages(admin_id):
    for slug in ("snake", "tetris", "microrts"):
        data = _zip_package(ROOT / "packaged-games" / slug)
        g, v = ugc.seed_game(admin_id, data)
        assert g["status"] == "published" and g["slug"] == slug, slug
        assert v["status"] == "active"
        assert v["meta"]["smoke"]["ok"] is True, v["meta"]["smoke"]
        # 包内声明随元数据入库
        m = v["meta"]["meta"]
        assert m["board"]["palette"]
    # 能力声明（G3 会话/模型面将消费这些字段）
    conn = ugc._db()
    try:
        rows = conn.execute(
            "SELECT slug FROM ugc_games WHERE status='published' "
            "ORDER BY id").fetchall()
    finally:
        conn.close()
    assert {r[0] for r in rows} >= {"snake", "tetris", "microrts"}
    snake_meta = ugc.latest_version(
        ugc.get_game_by_slug("snake")["id"])["meta"]["meta"]
    assert snake_meta["contract"]["protocol"] == "simple"
    assert snake_meta["contract"]["obs_mode"] == "rotwin"
    mr_meta = ugc.latest_version(
        ugc.get_game_by_slug("microrts")["id"])["meta"]["meta"]
    assert mr_meta["contract"]["protocol"] == "composite"
    assert mr_meta["pvp"]["options"] == {"opponent": "external"}
    assert mr_meta["opponents"] == ["worker_rush", "light_rush", "ranged_rush"]
