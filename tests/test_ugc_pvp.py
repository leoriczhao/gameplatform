"""UGC PvP capability (11 P4, D21): published pvp-enabled games get
rooms + matchmaking + ELO through the same surfaces as microrts; games that
don't declare pvp keep rejecting PvP."""
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
import registry  # noqa: E402

client = TestClient(main.app)

RPS_DIR = ROOT / "gdk-ug" / "examples" / "rock_paper_scissors"


def _rps_zip(slug: str = "rock-paper-scissors") -> bytes:
    """Build a zip from the real RPS example, with a test-safe slug."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        yaml = (RPS_DIR / "game.yaml").read_text()
        yaml = yaml.replace("slug: rock-paper-scissors", f"slug: {slug}")
        zf.writestr("game.yaml", yaml)
        zf.writestr("__init__.py", (RPS_DIR / "__init__.py").read_text())
        zf.writestr("README.md", (RPS_DIR / "README.md").read_text())
    return buf.getvalue()


def _user(name):
    r = client.post("/api/v1/auth/register",
                    json={"username": name, "password": "password123"})
    assert r.status_code == 200, r.text
    return r.json()


def _h(u):
    return {"Authorization": f"Bearer {u['token']}"}


def _publish(slug: str, admin: dict, author: dict) -> int:
    data = _rps_zip(slug)
    r = client.post("/api/v1/ugc/games",
                    files={"file": (f"{slug}.zip", data, "application/zip")},
                    data={"changelog": "init"}, headers=_h(author))
    assert r.status_code == 200, r.text
    gid = client.get("/api/v1/ugc/games", headers=_h(author)).json()["games"][0]["id"]
    assert client.post(f"/api/v1/ugc/games/{gid}/submit",
                       headers=_h(author)).status_code == 200
    assert client.post(f"/api/v1/admin/ugc/{gid}/approve",
                       headers=_h(admin)).status_code == 200
    return gid


@pytest.fixture
def admin(monkeypatch):
    monkeypatch.setenv("ADMIN_USERNAME", "ugcpvpadmin")
    monkeypatch.setenv("ADMIN_PASSWORD", "adminsecretp")
    admin_store.bootstrap_admin()
    r = client.post("/api/v1/auth/login",
                    json={"username": "ugcpvpadmin",
                          "password": "adminsecretp"})
    assert r.status_code == 200, r.text
    return r.json()


def test_non_pvp_game_rejects_pvp():
    A = _user("ugcpvp0")
    r = client.post("/api/v1/snake/play/sessions",
                    json={"kind": "pvp"}, headers=_h(A))
    assert r.status_code == 400
    assert "不支持" in r.text


def test_ugc_pvp_room_full_game(admin):
    A = _user("ugcpvp1")
    B = _user("ugcpvp2")
    slug = "rps-pvp-room"
    _publish(slug, admin, A)
    assert slug in registry.GAMES
    assert registry.GAMES[slug].pvp_enabled is True
    # 创建房间（p0 = A），B 加入
    r = client.post(f"/api/v1/{slug}/play/rooms", json={},
                    headers=_h(A))
    assert r.status_code == 200, r.text
    sid = r.json()["session"]["id"]
    # 房间公开列表里能看到（public 默认，等待中）
    rooms = client.get(f"/api/v1/{slug}/play/rooms",
                       headers=_h(A)).json()["rooms"]
    assert any(rm["id"] == sid for rm in rooms)
    r = client.post(f"/api/v1/{slug}/play/rooms/{sid}/join", json={},
                    headers=_h(B))
    assert r.status_code == 200, r.text
    # 双方各提交一个 choice 动作 -> 推进一局
    r = client.post(f"/api/v1/{slug}/play/sessions/{sid}/actions",
                    json={"actions": 0}, headers=_h(A))
    assert r.status_code == 200 and r.json()["advanced"] is False
    r = client.post(f"/api/v1/{slug}/play/sessions/{sid}/actions",
                    json={"actions": 1}, headers=_h(B))
    assert r.status_code == 200, r.text
    assert r.json()["advanced"] is True


def test_ugc_pvp_matchmaking(admin):
    A = _user("ugcpvp3")
    B = _user("ugcpvp4")
    slug = "rps-pvp-mm"
    _publish(slug, admin, A)
    # 快速匹配：B 入队即撮合（ELO 都在带内）
    r = client.post(f"/api/v1/{slug}/matchmaking/queue",
                    json={"mode": "casual"}, headers=_h(A))
    assert r.status_code == 200 and r.json()["queued"] is True
    r = client.post(f"/api/v1/{slug}/matchmaking/queue",
                    json={"mode": "casual"}, headers=_h(B))
    assert r.status_code == 200 and r.json()["matched"] is True
    sid = r.json()["session_id"]
    # 匹配到的房间可读、双方可玩（resign 收尾）
    r = client.get(f"/api/v1/{slug}/play/sessions/{sid}",
                   headers={"Authorization": f"Bearer {A['token']}"})
    assert r.status_code == 200 and r.json()["session"]["p1_joined"] is True
    client.post(f"/api/v1/{slug}/play/sessions/{sid}/leave", json={},
                headers=_h(A))
    client.delete(f"/api/v1/{slug}/matchmaking/queue", headers=_h(B))
