"""Room system tests (06 M1): public room list, create/join,
ranked/casual scoring, private rooms need an invite code."""
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


A1 = _user("roomsa1")
B1 = _user("roomsb1")
HA1 = {"Authorization": f"Bearer {A1['token']}"}
HB1 = {"Authorization": f"Bearer {B1['token']}"}


def test_rooms_public_list_but_create_requires_login():
    # 14 重构：公开房间列表游客可看（大厅实时房间数依赖）；创建/加入仍需登录
    assert client.get("/api/v1/microrts/play/rooms").status_code == 200
    r = client.post("/api/v1/microrts/play/rooms",
                    json={"mode": "casual", "visibility": "public"})
    assert r.status_code == 401


def test_legacy_bare_pvp_defaults_ranked_private():
    # 06 §4.2 compat: {kind:"pvp"} with no params == ranked/private
    r = client.post("/api/v1/microrts/play/sessions",
                    json={"kind": "pvp"}, headers=HA1)
    assert r.status_code == 200, r.text
    s = r.json()["session"]
    assert s["mode"] == "ranked"
    assert s["visibility"] == "private"
    assert s["status"] == "waiting"
    # private rooms never appear in the public list
    rooms = client.get("/api/v1/microrts/play/rooms", headers=HA1).json()["rooms"]
    assert all(rm["id"] != s["id"] for rm in rooms)
    client.post(f"/api/v1/microrts/play/sessions/{s['id']}/leave", headers=HA1)


def test_public_room_list_and_join_flow():
    A = _user("roomsa2")
    B = _user("roomsb2")
    HA = {"Authorization": f"Bearer {A['token']}"}
    HB = {"Authorization": f"Bearer {B['token']}"}

    r = client.post("/api/v1/microrts/play/rooms",
                    json={"mode": "casual", "visibility": "public"}, headers=HA)
    assert r.status_code == 200, r.text
    room = r.json()["session"]
    sid = room["id"]
    assert room["status"] == "waiting"
    assert room["mode"] == "casual" and room["visibility"] == "public"
    assert r.json()["side"] == "p0"

    # public room appears in the lobby list (with its invite for sharing)
    rooms = client.get("/api/v1/microrts/play/rooms", headers=HB).json()["rooms"]
    mine = [rm for rm in rooms if rm["id"] == sid]
    assert len(mine) == 1
    assert mine[0]["mode"] == "casual" and mine[0]["host"] == A["user"]["username"]

    # B joins without any invite code
    r = client.post(f"/api/v1/microrts/play/rooms/{sid}/join",
                    json={}, headers=HB)
    assert r.status_code == 200, r.text
    assert r.json()["side"] == "p1"
    assert r.json()["session"]["status"] == "active"
    assert r.json()["session"]["p1_joined"] is True

    # full rooms leave the public list
    rooms = client.get("/api/v1/microrts/play/rooms", headers=HA).json()["rooms"]
    assert all(rm["id"] != sid for rm in rooms)

    # both sides can play: B submits, then A submits -> tick advances
    r = client.post(f"/api/v1/microrts/play/sessions/{sid}/actions",
                    json={"actions": []}, headers=HB)
    assert r.json()["advanced"] is False
    r = client.post(f"/api/v1/microrts/play/sessions/{sid}/actions",
                    json={"actions": []}, headers=HA)
    assert r.json()["advanced"] is True and r.json()["tick"] == 1


def test_casual_does_not_change_elo_but_records_match():
    A = _user("roomsa3")
    B = _user("roomsb3")
    HA = {"Authorization": f"Bearer {A['token']}"}
    HB = {"Authorization": f"Bearer {B['token']}"}

    r = client.post("/api/v1/microrts/play/rooms",
                    json={"mode": "casual", "visibility": "public"}, headers=HA)
    sid = r.json()["session"]["id"]
    client.post(f"/api/v1/microrts/play/rooms/{sid}/join", json={}, headers=HB)

    # A resigns -> B wins, match recorded with mode=casual
    r = client.post(f"/api/v1/microrts/play/sessions/{sid}/leave", headers=HA)
    assert r.status_code == 200 and r.json()["winner"] == 1

    r = client.get("/api/v1/matches", headers=HA)
    matches = [m for m in r.json()["matches"]
               if m["kind"] == "pvp" and m["status"] == "finished"
               and m["result"]["cause"] == "resigned"]
    assert matches and matches[-1]["result"]["mode"] == "casual"

    # neither player gained a rating row (both stay at the 1200 default)
    r = client.get("/api/v1/ratings/microrts", headers=HA)
    names = {i["name"] for i in r.json()["items"]}
    assert A["user"]["username"] not in names
    assert B["user"]["username"] not in names


def test_ranked_room_updates_elo():
    A = _user("roomsa4")
    B = _user("roomsb4")
    HA = {"Authorization": f"Bearer {A['token']}"}
    HB = {"Authorization": f"Bearer {B['token']}"}

    r = client.post("/api/v1/microrts/play/rooms",
                    json={"mode": "ranked", "visibility": "public"}, headers=HA)
    assert r.json()["session"]["mode"] == "ranked"
    sid = r.json()["session"]["id"]
    client.post(f"/api/v1/microrts/play/rooms/{sid}/join", json={}, headers=HB)

    # A resigns -> B wins and both ratings move off 1200
    client.post(f"/api/v1/microrts/play/sessions/{sid}/leave", headers=HA)
    r = client.get("/api/v1/ratings/microrts", headers=HA)
    ratings = {i["name"]: i for i in r.json()["items"]}
    assert ratings[A["user"]["username"]]["rating"] < 1200
    assert ratings[B["user"]["username"]]["rating"] > 1200
    assert ratings[A["user"]["username"]]["games"] == 1

    r = client.get("/api/v1/matches", headers=HA)
    ranked = [m for m in r.json()["matches"]
              if m["kind"] == "pvp" and m["result"]["mode"] == "ranked"]
    assert ranked and ranked[-1]["result"]["winner"] == 1


def test_private_room_requires_invite():
    A = _user("roomsa5")
    B = _user("roomsb5")
    HA = {"Authorization": f"Bearer {A['token']}"}
    HB = {"Authorization": f"Bearer {B['token']}"}

    r = client.post("/api/v1/microrts/play/rooms",
                    json={"mode": "casual", "visibility": "private"}, headers=HA)
    sid = r.json()["session"]["id"]
    invite = r.json()["invite"]
    assert r.json()["session"]["visibility"] == "private"

    # not listed publicly
    rooms = client.get("/api/v1/microrts/play/rooms", headers=HB).json()["rooms"]
    assert all(rm["id"] != sid for rm in rooms)

    # join without / with wrong code -> 400; correct code -> 200
    r = client.post(f"/api/v1/microrts/play/rooms/{sid}/join",
                    json={}, headers=HB)
    assert r.status_code == 400
    r = client.post(f"/api/v1/microrts/play/rooms/{sid}/join",
                    json={"invite": "ZZZZZZ"}, headers=HB)
    assert r.status_code == 400
    r = client.post(f"/api/v1/microrts/play/rooms/{sid}/join",
                    json={"invite": invite.lower()}, headers=HB)  # case-insensitive
    assert r.status_code == 200, r.text
    assert r.json()["session"]["status"] == "active"


def test_cannot_join_own_or_missing_room():
    A = _user("roomsa6")
    B = _user("roomsb6")
    C = _user("roomsc6")
    HA = {"Authorization": f"Bearer {A['token']}"}
    HB = {"Authorization": f"Bearer {B['token']}"}
    HC = {"Authorization": f"Bearer {C['token']}"}

    r = client.post("/api/v1/microrts/play/rooms",
                    json={"mode": "casual", "visibility": "public"}, headers=HA)
    sid = r.json()["session"]["id"]

    # missing room -> 404
    r = client.post("/api/v1/microrts/play/rooms/nonexistent/join",
                    json={}, headers=HB)
    assert r.status_code == 404

    # own room -> 400
    r = client.post(f"/api/v1/microrts/play/rooms/{sid}/join",
                    json={}, headers=HA)
    assert r.status_code == 400

    # second joiner after it is full -> 400
    client.post(f"/api/v1/microrts/play/rooms/{sid}/join", json={}, headers=HB)
    r = client.post(f"/api/v1/microrts/play/rooms/{sid}/join",
                    json={}, headers=HC)
    assert r.status_code == 400


def test_rooms_list_mode_filter_and_sessions_params():
    A = _user("roomsa7")
    HA = {"Authorization": f"Bearer {A['token']}"}

    r = client.post("/api/v1/microrts/play/rooms",
                    json={"mode": "ranked", "visibility": "public"}, headers=HA)
    ranked_id = r.json()["session"]["id"]
    # the legacy sessions endpoint also accepts the new params
    r = client.post("/api/v1/microrts/play/sessions",
                    json={"kind": "pvp", "mode": "casual",
                          "visibility": "public", "settings": {"seed": 42}},
                    headers=HA)
    assert r.status_code == 200, r.text
    casual_id = r.json()["session"]["id"]
    assert r.json()["session"]["visibility"] == "public"

    rooms = client.get("/api/v1/microrts/play/rooms", headers=HA).json()["rooms"]
    ids = {rm["id"]: rm for rm in rooms}
    assert ids[ranked_id]["mode"] == "ranked"
    assert ids[casual_id]["mode"] == "casual"

    ranked_only = client.get(
        "/api/v1/microrts/play/rooms?mode=ranked", headers=HA).json()["rooms"]
    assert all(rm["mode"] == "ranked" for rm in ranked_only)
    assert casual_id not in [rm["id"] for rm in ranked_only]

    # invalid filter -> 400
    assert client.get("/api/v1/microrts/play/rooms?mode=banana",
                      headers=HA).status_code == 400

    # cleanup: cancel both waiting rooms
    client.post(f"/api/v1/microrts/play/sessions/{ranked_id}/leave", headers=HA)
    client.post(f"/api/v1/microrts/play/sessions/{casual_id}/leave", headers=HA)
