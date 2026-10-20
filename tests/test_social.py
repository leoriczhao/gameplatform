"""Social tests (v1.0-b): profile, friends, room chat, notifications."""
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


def _user(name):
    r = client.post("/api/v1/auth/register",
                    json={"username": name, "password": "password123"})
    assert r.status_code == 200, r.text
    return r.json()


def _h(u):
    return {"Authorization": f"Bearer {u['token']}"}


def test_profile_requires_login_and_roundtrip():
    assert client.get("/api/v1/profile").status_code == 401
    A = _user("soca1")
    r = client.get("/api/v1/profile", headers=_h(A))
    assert r.status_code == 200
    p = r.json()["profile"]
    assert p["username"] == "soca1" and p["nickname"] == "soca1"
    assert p["avatar"] == "" and p["signature"] == ""

    r = client.put("/api/v1/profile",
                   json={"nickname": "爱丽丝", "avatar": "🦊",
                         "signature": "  打工人，摸鱼王  "}, headers=_h(A))
    assert r.status_code == 200, r.text
    p = r.json()["profile"]
    assert p["nickname"] == "爱丽丝" and p["avatar"] == "🦊"
    assert p["signature"] == "打工人，摸鱼王"

    # partial update keeps other fields; bad input rejected
    r = client.put("/api/v1/profile", json={"nickname": ""}, headers=_h(A))
    assert r.status_code == 400
    r = client.put("/api/v1/profile", json={"signature": "新签名"}, headers=_h(A))
    p = r.json()["profile"]
    assert p["signature"] == "新签名" and p["nickname"] == "爱丽丝"

    # nickname propagates to the auth /me view
    r = client.get("/api/v1/auth/me", headers=_h(A))
    assert r.json()["user"]["nickname"] == "爱丽丝"


def test_friends_add_list_remove_symmetric():
    A = _user("soca2")
    B = _user("socb2")
    # unknown user / self / duplicate
    assert client.post("/api/v1/friends", json={"username": "nobody_xx"},
                       headers=_h(A)).status_code == 404
    assert client.post("/api/v1/friends", json={"username": "soca2"},
                       headers=_h(A)).status_code == 400
    r = client.post("/api/v1/friends", json={"username": "socb2"}, headers=_h(A))
    assert r.status_code == 200, r.text
    assert r.json()["friend"]["username"] == "socb2"
    assert client.post("/api/v1/friends", json={"username": "socb2"},
                       headers=_h(A)).status_code == 400

    # symmetric: both sides see each other
    fa = client.get("/api/v1/friends", headers=_h(A)).json()["friends"]
    fb = client.get("/api/v1/friends", headers=_h(B)).json()["friends"]
    assert [f["username"] for f in fa] == ["socb2"]
    assert [f["username"] for f in fb] == ["soca2"]

    # B got a friend-add notification
    nb = client.get("/api/v1/notifications", headers=_h(B)).json()
    assert nb["unread"] >= 1
    assert any(n["kind"] == "friend_add" and "soca2" in n["body"]
               for n in nb["items"])

    # remove deletes both directions
    bid = fa[0]["id"]  # B's user id, as seen from A's list
    client.delete(f"/api/v1/friends/{bid}", headers=_h(A))
    assert client.get("/api/v1/friends", headers=_h(A)).json()["friends"] == []
    assert client.get("/api/v1/friends", headers=_h(B)).json()["friends"] == []


def test_friends_requires_login():
    assert client.get("/api/v1/friends").status_code == 401
    assert client.post("/api/v1/friends", json={"username": "x"}).status_code == 401


def test_room_chat_participants_only_and_since_cursor():
    A = _user("soca3")
    B = _user("socb3")
    C = _user("socc3")
    r = client.post("/api/v1/microrts/play/rooms",
                    json={"mode": "casual", "visibility": "private"}, headers=_h(A))
    sid = r.json()["session"]["id"]
    client.post(f"/api/v1/microrts/play/rooms/{sid}/join",
                json={"invite": r.json()["invite"]}, headers=_h(B))

    # third party cannot read or write
    assert client.get(f"/api/v1/microrts/play/sessions/{sid}/chat?since=0",
                      headers=_h(C)).status_code == 403
    assert client.post(f"/api/v1/microrts/play/sessions/{sid}/chat",
                       json={"text": "hi"}, headers=_h(C)).status_code == 403

    # A and B exchange messages
    r = client.post(f"/api/v1/microrts/play/sessions/{sid}/chat",
                    json={"text": "  你好，我是 A  "}, headers=_h(A))
    assert r.status_code == 200, r.text
    m1 = r.json()["message"]
    assert m1["text"] == "你好，我是 A" and m1["nickname"] == "soca3"
    r = client.post(f"/api/v1/microrts/play/sessions/{sid}/chat",
                    json={"text": "收到！"}, headers=_h(B))
    m2 = r.json()["message"]

    # empty text rejected
    assert client.post(f"/api/v1/microrts/play/sessions/{sid}/chat",
                       json={"text": "   "}, headers=_h(A)).status_code == 400

    # B polls from 0 -> sees both in order; since cursor skips old messages
    r = client.get(f"/api/v1/microrts/play/sessions/{sid}/chat?since=0", headers=_h(B))
    msgs = r.json()["messages"]
    assert [m["id"] for m in msgs] == [m1["id"], m2["id"]]
    assert r.json()["next_since"] == m2["id"]
    r = client.get(f"/api/v1/microrts/play/sessions/{sid}/chat?since={m1['id']}",
                   headers=_h(B))
    assert [m["id"] for m in r.json()["messages"]] == [m2["id"]]
    # history survives a fresh poll (persisted, not in-memory)
    r = client.get(f"/api/v1/microrts/play/sessions/{sid}/chat?since=0", headers=_h(A))
    assert len(r.json()["messages"]) == 2


def test_notifications_read_flow():
    A = _user("soca4")
    B = _user("socb4")
    r = client.get("/api/v1/notifications/unread", headers=_h(A))
    assert r.json()["unread"] == 0
    client.post("/api/v1/friends", json={"username": "socb4"}, headers=_h(A))
    r = client.get("/api/v1/notifications/unread", headers=_h(B))
    assert r.json()["unread"] >= 1
    client.post("/api/v1/notifications/read", headers=_h(B))
    r = client.get("/api/v1/notifications", headers=_h(B))
    assert r.json()["unread"] == 0
    assert all(n["read"] for n in r.json()["items"])
