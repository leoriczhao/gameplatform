"""Ops tests (v1.0-d): announcements, reports, admin console, ban."""
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

import admin as admin_store  # noqa: E402
import main  # noqa: E402

client = TestClient(main.app)


def _user(name):
    r = client.post("/api/v1/auth/register",
                    json={"username": name, "password": "password123"})
    assert r.status_code == 200, r.text
    return r.json()


def _h(u):
    return {"Authorization": f"Bearer {u['token']}"}


def _admin(monkeypatch, name="opsadmin1", pw="adminsecret123"):
    monkeypatch.setenv("ADMIN_USERNAME", name)
    monkeypatch.setenv("ADMIN_PASSWORD", pw)
    admin_store.bootstrap_admin()
    r = client.post("/api/v1/auth/login",
                    json={"username": name, "password": pw})
    assert r.status_code == 200, r.text
    return r.json()


def test_announcements_public_and_admin_managed(monkeypatch):
    A = _admin(monkeypatch)
    # empty at first, public read works without auth
    r = client.get("/api/v1/announcements")
    assert r.status_code == 200 and r.json()["items"] == []

    r = client.post("/api/v1/admin/announcements",
                    json={"body": "  今晚 22:00 停机维护  "}, headers=_h(A))
    assert r.status_code == 200, r.text
    aid = r.json()["announcement"]["id"]
    assert r.json()["announcement"]["body"] == "今晚 22:00 停机维护"

    r = client.get("/api/v1/announcements")
    assert [a["id"] for a in r.json()["items"]] == [aid]

    # deactivate -> disappears from the public feed
    r = client.post(f"/api/v1/admin/announcements/{aid}/active",
                    json={"status": "off"}, headers=_h(A))
    assert r.status_code == 200
    assert client.get("/api/v1/announcements").json()["items"] == []


def test_reports_flow(monkeypatch):
    A = _user("opsa1")
    B = _user("opsb1")
    AD = _admin(monkeypatch)
    # login required to report
    assert client.post("/api/v1/reports",
                       json={"target_type": "user", "target_id": 1}).status_code == 401
    r = client.post("/api/v1/reports",
                    json={"target_type": "user",
                          "target_id": B["user"]["id"],
                          "reason": "疑似刷分"}, headers=_h(A))
    assert r.status_code == 200, r.text
    assert r.json()["report"]["status"] == "open"

    # bad target type rejected
    assert client.post("/api/v1/reports",
                       json={"target_type": "banana", "target_id": 1},
                       headers=_h(A)).status_code == 400

    # admin sees and resolves it
    r = client.get("/api/v1/admin/reports", headers=_h(AD))
    reps = r.json()["reports"]
    assert any(x["target_type"] == "user" and x["reason"] == "疑似刷分"
               and x["status"] == "open" and x["reporter"] == "opsa1"
               for x in reps)
    rid = reps[0]["id"]
    r = client.post(f"/api/v1/admin/reports/{rid}/status",
                    json={"status": "resolved"}, headers=_h(AD))
    assert r.status_code == 200
    r = client.get("/api/v1/admin/reports?status=resolved", headers=_h(AD))
    assert any(x["id"] == rid and x["status"] == "resolved"
               for x in r.json()["reports"])


def test_admin_auth_and_ban_flow(monkeypatch):
    A = _user("opsa2")
    B = _user("opsb2")
    AD = _admin(monkeypatch)
    # non-admin cannot touch the console
    assert client.get("/api/v1/admin/users", headers=_h(A)).status_code == 403
    assert client.get("/api/v1/admin/users").status_code == 401

    # ban B -> login rejected; unban -> login works again
    r = client.post(f"/api/v1/admin/users/{B['user']['id']}/status",
                    json={"status": "banned"}, headers=_h(AD))
    assert r.status_code == 200, r.text
    assert client.post("/api/v1/auth/login",
                       json={"username": "opsb2",
                             "password": "password123"}).status_code == 401
    r = client.post(f"/api/v1/admin/users/{B['user']['id']}/status",
                    json={"status": "active"}, headers=_h(AD))
    assert r.status_code == 200
    assert client.post("/api/v1/auth/login",
                       json={"username": "opsb2",
                             "password": "password123"}).status_code == 200

    # self-ban and admin-ban are refused
    assert client.post(f"/api/v1/admin/users/{AD['user']['id']}/status",
                       json={"status": "banned"}, headers=_h(AD)).status_code == 400
    r = client.post(f"/api/v1/admin/users/{A['user']['id']}/status",
                    json={"status": "banned"}, headers=_h(AD))
    assert r.status_code == 200  # A is a regular user: ok to ban; undo
    client.post(f"/api/v1/admin/users/{A['user']['id']}/status",
                json={"status": "active"}, headers=_h(AD))


def test_dashboard_and_lists(monkeypatch):
    A = _user("opsa3")
    AD = _admin(monkeypatch)
    r = client.get("/api/v1/admin/dashboard", headers=_h(AD))
    assert r.status_code == 200, r.text
    d = r.json()
    for key in ("users_total", "users_new_24h", "dau_24h",
                "active_sessions", "matches_total", "matches_24h",
                "models_active", "reports_open"):
        assert key in d and isinstance(d[key], int), key
    assert d["users_total"] >= 2
    r = client.get("/api/v1/admin/users", headers=_h(AD))
    assert any(u["username"] == "opsa3" for u in r.json()["users"])
    r = client.get("/api/v1/admin/models", headers=_h(AD))
    assert r.status_code == 200 and isinstance(r.json()["models"], list)
    r = client.get("/api/v1/admin/matches", headers=_h(AD))
    assert r.status_code == 200 and isinstance(r.json()["matches"], list)
