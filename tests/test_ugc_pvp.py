"""UGC PvP capability (11 P4, D21): published pvp-enabled games get v2
rooms + v2 matchmaking + ELO through the same surfaces as microrts; games that
don't declare pvp keep rejecting PvP. The v1 play/room session API is gone
(M4 / design 17 §9)."""
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
import ugc_runner  # noqa: E402

client = TestClient(main.app)


@pytest.fixture(autouse=True)
def _restore_registry():
    """Published test games never leak into other test modules."""
    before = set(registry.GAMES)
    yield
    for slug in set(registry.GAMES) - before:
        registry.unregister(slug)
        ugc_runner.drop_worker(slug)


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


def _rps_two_seat_no_pvp_zip(slug: str) -> bytes:
    """Two seats declared, but no pvp declaration: humans may never fight."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        yaml = (RPS_DIR / "game.yaml").read_text()
        yaml = yaml.replace("slug: rock-paper-scissors", f"slug: {slug}")
        yaml = yaml.split("\npvp:")[0] + "\nseats: 2\n"
        zf.writestr("game.yaml", yaml)
        zf.writestr("__init__.py", (RPS_DIR / "__init__.py").read_text())
    return buf.getvalue()


def _publish(slug: str, admin: dict, author: dict, data: bytes | None = None) -> int:
    data = data if data is not None else _rps_zip(slug)
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


def _room(a: dict, slug: str, **extra) -> dict:
    r = client.post("/api/v2/matches", headers=_h(a), json={
        "game": slug,
        "seats": [{"seat": "p0", "occupant": "me", "controller": {"type": "human"}},
                  {"seat": "p1", "occupant": None, "controller": {"type": "human"}}],
        **extra})
    assert r.status_code == 201, r.text
    return r.json()


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


def test_non_pvp_game_rejects_pvp(admin):
    A = _user("ugcpvp0")
    slug = "rps-nopvp"
    _publish(slug, admin, A, data=_rps_two_seat_no_pvp_zip(slug))
    assert slug in registry.GAMES and registry.GAMES[slug].pvp_enabled is False
    r = client.post("/api/v2/matches", headers=_h(A), json={
        "game": slug,
        "seats": [{"seat": "p0", "occupant": "me", "controller": {"type": "human"}},
                  {"seat": "p1", "occupant": None, "controller": {"type": "human"}}]})
    assert r.status_code == 400, r.text
    assert r.json()["detail"]["code"] == "no_pvp"
    assert "不支持" in r.text


def test_ugc_pvp_room_full_game(admin):
    A = _user("ugcpvp1")
    B = _user("ugcpvp2")
    slug = "rps-pvp-room"
    _publish(slug, admin, A)
    assert slug in registry.GAMES
    assert registry.GAMES[slug].pvp_enabled is True
    # 创建 v2 房间（p0 = A），公开列表可见；B 加入后对局开始
    room = _room(A, slug)
    sid = room["id"]
    assert room["status"] == "waiting" and room["kind"] == "pvp"
    rooms = client.get(f"/api/v2/matches?game={slug}",
                       headers=_h(A)).json()["rooms"]
    assert any(rm["id"] == sid for rm in rooms)
    r = client.post(f"/api/v2/matches/{sid}/seats/p1/join", json={},
                    headers=_h(B))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "active" and r.json()["you"]["seat"] == "p1"
    assert client.get(f"/api/v2/matches/{sid}", headers=_h(A)).json()["kind"] == "pvp"
    # 认输收尾，对局记录落库（ELO 只在 ranked；casual 同样记录）
    assert client.post(f"/api/v2/matches/{sid}/resign",
                       headers=_h(B)).status_code == 200
    rec = client.get(f"/api/v1/matches", headers=_h(A)).json()["matches"]
    row = next(m for m in rec if m.get("uid") == sid)
    assert row["kind"] == "pvp" and row["status"] == "finished"


def test_ugc_pvp_matchmaking(admin):
    A = _user("ugcpvp3")
    B = _user("ugcpvp4")
    slug = "rps-pvp-mm"
    _publish(slug, admin, A)
    # 快速匹配：B 入队即撮合（ELO 都在带内），返回 v2 match_id
    r = client.post(f"/api/v2/{slug}/matchmaking/queue",
                    json={"mode": "casual"}, headers=_h(A))
    assert r.status_code == 200 and r.json()["queued"] is True
    r = client.post(f"/api/v2/{slug}/matchmaking/queue",
                    json={"mode": "casual"}, headers=_h(B))
    assert r.status_code == 200 and r.json()["matched"] is True
    mid = r.json()["match_id"]
    # 匹配到的对局可读、双方已入座
    view = client.get(f"/api/v2/matches/{mid}", headers=_h(A)).json()
    assert view["status"] == "active" and view["kind"] == "pvp"
    assert [s["occupant"]["user_id"] for s in view["seats"]] == \
        [A["user"]["id"], B["user"]["id"]]
    assert client.get(f"/api/v2/{slug}/matchmaking/status",
                      headers=_h(A)).json()["match_id"] == mid
    client.post(f"/api/v2/matches/{mid}/resign", headers=_h(A))
    client.delete(f"/api/v2/{slug}/matchmaking/queue", headers=_h(B))
