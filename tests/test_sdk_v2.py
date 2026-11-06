"""SDK 1.0: PlatformClient/SessionClient speak the v2 matches protocol.

Pure offline tests: the instance method PlatformClient._req is replaced with a
scripted fake, so the v2 path, request body and act() polling semantics are
asserted without a backend, network or sleeps. The OpenEnv layer is covered by
tests/test_sdk_training.py.
"""
import os
import sys
from pathlib import Path

import pytest

# openenv -> gradio -> httpx parses NO_PROXY at import time; this machine has
# bare IPv6 entries there (see sdk/README.md). Sanitise before importing the SDK.
for _key in ("NO_PROXY", "no_proxy"):
    _entries = [e.strip() for e in os.environ.get(_key, "").split(",")
                if e.strip() and not e.strip().startswith("[")]
    _entries = [e for e in _entries if ":" not in e]
    for _loopback in ("127.0.0.1", "localhost"):
        if _loopback not in _entries:
            _entries.append(_loopback)
    os.environ[_key] = ",".join(_entries)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sdk"))

import gameplatform  # noqa: E402
from gameplatform import PlatformClient, PlatformError, SessionClient  # noqa: E402


def view(*, id="m1", status="active", tick=0, to_act=("p0",), you="p0",
         submitted=None, seats=None, result=None, **extra):
    """Build a MatchView-shaped snapshot (design 17 §5) for the fake server."""
    if seats is None:
        seats = [{"seat": "p0", "submitted": False},
                 {"seat": "p1", "submitted": False}]
    if submitted:
        seats = [{**s, "submitted": s["seat"] in submitted} for s in seats]
    body = {"id": id, "game": "microrts", "kind": "pvp", "mode": "casual",
            "visibility": "public", "status": status, "result": result,
            "seats": seats, "you": {"seat": you}, "tick": tick,
            "frame": {"tick": tick}, "events": [], "to_act": list(to_act),
            "deadline_at": None, "frames": tick + 1, "marks": [], "chat": [],
            "invite": None, "server_time": 0}
    body.update(extra)
    return body


class FakeAPI:
    """Scripted stand-in for PlatformClient._req, injected per test."""

    def __init__(self):
        self.calls = []
        self.routes = {}
        self.client = None

    def on(self, method, path, *replies):
        self.routes[(method, path)] = list(replies)
        return self

    def __call__(self, method, path, **kw):
        self.calls.append({"method": method, "path": path, "json": kw.get("json")})
        replies = self.routes.get((method, path))
        if replies is None:
            raise AssertionError(f"unexpected request: {method} {path}")
        if not replies:
            raise AssertionError(f"no scripted reply left for {method} {path}")
        reply = replies[0]
        if len(replies) > 1 or not callable(reply):
            replies.pop(0)
        if callable(reply):
            reply = reply()
        if isinstance(reply, Exception):
            raise reply
        return reply

    def paths(self):
        return [(c["method"], c["path"]) for c in self.calls]


class _Response:
    def __init__(self, status, payload):
        self.status_code = status
        self.ok = 200 <= status < 300
        self.payload = payload

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class _HTTP:
    """Minimal requests.Session look-alike exercising PlatformClient._req."""

    def __init__(self, response):
        self.response = response
        self.calls = []

    def request(self, method, url, **kw):
        self.calls.append((method, url, kw))
        return self.response


@pytest.fixture
def api(monkeypatch):
    fake = FakeAPI()
    client = PlatformClient(base_url="http://sdk.test", token="jwt")
    monkeypatch.setattr(client, "_req", fake)
    fake.client = client
    return fake


@pytest.fixture
def client(api):
    return api.client


# --------------------------------------------------------------- release

def test_sdk_release_is_major_version_1():
    assert gameplatform.__version__ == "1.0.0"
    assert gameplatform.SessionClient is SessionClient


# ------------------------------------------------------- PlatformClient v2

def test_create_match_posts_two_model_seats_to_v2(api, client):
    api.on("POST", "/api/v2/matches", view(id="abc123", to_act=[]))
    uid = client.create_match("microrts", model_a=11, model_b="ai:light_rush")
    assert uid == "abc123"
    assert api.paths() == [("POST", "/api/v2/matches")]
    assert api.calls[0]["json"] == {
        "game": "microrts",
        "seats": [
            {"seat": "p0", "occupant": None,
             "controller": {"type": "model", "model_id": 11}},
            {"seat": "p1", "occupant": None,
             "controller": {"type": "ai", "strategy": "light_rush"}},
        ],
    }


def test_create_match_accepts_model_id_and_bare_strategy(api, client):
    api.on("POST", "/api/v2/matches", view(id="x"), view(id="y"))
    client.create_match("microrts", model_a=1, model_b=7)
    client.create_match("microrts", model_a=1, model_b="worker_rush")
    assert api.calls[0]["json"]["seats"][1]["controller"] == {
        "type": "model", "model_id": 7}
    assert api.calls[1]["json"]["seats"][1]["controller"] == {
        "type": "ai", "strategy": "worker_rush"}


def test_wait_match_polls_v2_snapshot_until_terminal(api, client):
    api.on("GET", "/api/v2/matches/u1", view(status="active"),
           view(status="finished", result={"winner": "p0", "cause": "done"}))
    result = client.wait_match("u1", timeout=1.0, poll=0)
    assert result["status"] == "finished" and result["result"]["winner"] == "p0"
    assert api.paths() == [("GET", "/api/v2/matches/u1")] * 2


def test_wait_match_times_out(api, client):
    api.on("GET", "/api/v2/matches/u1", lambda: view(status="active"))
    with pytest.raises(TimeoutError):
        client.wait_match("u1", timeout=0.02, poll=0)


def test_match_replay_assembles_frames_pages(api, client):
    api.on("GET", "/api/v2/matches/u1/frames?from=0&limit=2",
           {"frames": [{"tick": 0}, {"tick": 1}], "next": 2, "total": 3})
    api.on("GET", "/api/v2/matches/u1/frames?from=2&limit=2",
           {"frames": [{"tick": 2}], "next": None, "total": 3})
    out = client.match_replay("u1", limit=2)
    assert out == {"id": "u1", "total": 3,
                   "frames": [{"tick": 0}, {"tick": 1}, {"tick": 2}]}
    assert api.paths() == [
        ("GET", "/api/v2/matches/u1/frames?from=0&limit=2"),
        ("GET", "/api/v2/matches/u1/frames?from=2&limit=2")]


def test_my_matches_keeps_v1_history_and_live_uses_v2(api, client):
    api.on("GET", "/api/v1/matches", {"matches": [{"match_id": 1}]})
    api.on("GET", "/api/v2/me/matches", {"matches": [view(id="live1")]})
    assert client.my_matches() == [{"match_id": 1}]
    assert client.my_live_matches()[0]["id"] == "live1"
    assert api.paths() == [("GET", "/api/v1/matches"),
                           ("GET", "/api/v2/me/matches")]


def test_create_room_posts_v2_pvp_seats(api, client):
    api.on("POST", "/api/v2/matches",
           view(id="room1", invite="ABC123", status="waiting", to_act=[]))
    room = client.create_room("microrts", mode="ranked",
                              visibility="private", seed=7)
    assert room["id"] == "room1" and room["invite"] == "ABC123"
    body = api.calls[0]["json"]
    assert body["game"] == "microrts"
    assert body["mode"] == "ranked" and body["visibility"] == "private"
    assert body["settings"] == {"seed": 7}
    assert body["seats"] == [
        {"seat": "p0", "occupant": "me", "controller": {"type": "human"}},
        {"seat": "p1", "occupant": None, "controller": {"type": "human"}},
    ]


def test_join_room_and_lobby_use_v2_paths(api, client):
    api.on("POST", "/api/v2/matches/room1/seats/p1/join",
           view(id="room1", you="p1"))
    api.on("GET", "/api/v2/matches?game=microrts&mode=casual",
           {"rooms": [{"id": "room1"}]})
    landed = client.join_room("room1", invite="ABC123")
    assert landed["you"]["seat"] == "p1"
    assert api.calls[0]["json"] == {"invite": "ABC123"}
    assert client.lobby("microrts", mode="casual") == [{"id": "room1"}]


def test_quick_match_polls_v2_queue_until_match_id(api, client):
    api.on("POST", "/api/v2/microrts/matchmaking/queue",
           {"queued": True, "matched": False, "match_id": None})
    api.on("GET", "/api/v2/microrts/matchmaking/status",
           {"queued": True, "matched": False, "match_id": None},
           {"queued": False, "matched": True, "match_id": "u42"})
    assert client.quick_match("microrts", mode="ranked",
                              timeout=1.0, poll=0) == "u42"
    assert api.paths() == [
        ("POST", "/api/v2/microrts/matchmaking/queue"),
        ("GET", "/api/v2/microrts/matchmaking/status"),
        ("GET", "/api/v2/microrts/matchmaking/status")]
    assert api.calls[0]["json"] == {"mode": "ranked"}


def test_quick_match_errors_when_queue_entry_vanished(api, client):
    api.on("POST", "/api/v2/microrts/matchmaking/queue",
           {"queued": False, "matched": False, "match_id": None})
    with pytest.raises(PlatformError) as excinfo:
        client.quick_match("microrts", timeout=0.1, poll=0)
    assert excinfo.value.code == "not_queued"


def test_queue_status_and_cancel_queue_paths(api, client):
    api.on("GET", "/api/v2/microrts/matchmaking/status", {"queued": True})
    api.on("DELETE", "/api/v2/microrts/matchmaking/queue", {"removed": True})
    assert client.queue_status("microrts") == {"queued": True}
    assert client.cancel_queue("microrts") == {"removed": True}


def test_send_chat_posts_v2_room_chat(api, client):
    api.on("POST", "/api/v2/matches/u1/chat",
           {"message": {"id": 3, "text": "gg"}})
    assert client.send_chat("u1", "gg") == {"id": 3, "text": "gg"}
    assert api.calls[0]["json"] == {"text": "gg"}


def test_req_surfaces_v2_error_code_and_message():
    client = PlatformClient(base_url="http://sdk.test")
    client.http = _HTTP(_Response(
        409, {"detail": {"code": "stale_tick", "message": "局面已更新", "current": 3}}))
    with pytest.raises(PlatformError) as excinfo:
        client._req("POST", "/api/v2/matches/u1/actions",
                    json={"tick": 0, "action": 0})
    err = excinfo.value
    assert err.code == "stale_tick" and err.status == 409
    assert str(err) == "局面已更新"
    assert err.detail["detail"]["current"] == 3
    assert client.http.calls[0][1] == "http://sdk.test/api/v2/matches/u1/actions"


def test_req_success_and_empty_204():
    client = PlatformClient(base_url="http://sdk.test/")
    client.http = _HTTP(_Response(200, {"ok": True}))
    assert client._req("GET", "/x") == {"ok": True}
    assert client.http.calls[0][1] == "http://sdk.test/x"
    client.http = _HTTP(_Response(204, None))
    assert client._req("DELETE", "/y") == {}


def test_req_plain_string_detail_still_raises():
    client = PlatformClient(base_url="http://sdk.test")
    client.http = _HTTP(_Response(401, {"detail": "请先登录"}))
    with pytest.raises(PlatformError) as excinfo:
        client._req("GET", "/api/v2/me/matches")
    assert str(excinfo.value) == "请先登录"
    assert excinfo.value.code is None


def test_v1_play_room_and_quick_match_helpers_are_gone():
    for name in ("list_rooms", "join_quick_match", "active_games",
                 "_open_matched_session", "chat_since"):
        assert not hasattr(PlatformClient, name), name


def test_sdk_python_sources_have_no_v1_protocol_strings():
    # split literals so the repository grep for the removed protocol is clean
    forbidden = ("play/" + "sessions", "play/" + "rooms", "play/" + "active",
                 "expected" + "_tick", "rebuild" + "Replay")
    for path in (ROOT / "sdk").rglob("*.py"):
        source = path.read_text()
        for token in forbidden:
            assert token not in source, f"{token} in {path}"


# -------------------------------------------------------- SessionClient v2

def test_session_attaches_to_match_id(client):
    session = client.session("microrts", "m1")
    assert isinstance(session, SessionClient)
    assert session.id == "m1" and session.game == "microrts"


def test_start_pve_default_seats_sends_v2_practice_body(api, client):
    created = view(id="pve1", to_act=["p0"])
    api.on("POST", "/api/v2/matches", created)
    session = client.session("snake")
    assert session.start_pve(seed=7) is session
    assert session.id == "pve1" and session.match is created
    assert api.paths() == [("POST", "/api/v2/matches")]
    assert api.calls[0]["json"] == {
        "game": "snake", "mode": "practice", "visibility": "unlisted",
        "settings": {"seed": 7}}


def test_start_pve_with_opponent_builds_two_seats(api, client):
    api.on("POST", "/api/v2/matches", view(id="pve2"))
    session = client.session("microrts").start_pve(
        opponent="worker_rush",
        controller={"type": "model", "model_id": 12})
    assert session.id == "pve2"
    assert api.calls[0]["json"]["seats"] == [
        {"seat": "p0", "occupant": "me",
         "controller": {"type": "model", "model_id": 12}},
        {"seat": "p1", "occupant": None,
         "controller": {"type": "ai", "strategy": "worker_rush"}},
    ]


def test_start_pve_controller_only_switches_my_seat(api, client):
    api.on("POST", "/api/v2/matches", view(id="pve3"))
    api.on("POST", "/api/v2/matches/pve3/controller", view(id="pve3"))
    session = client.session("snake").start_pve(
        controller={"type": "model", "model_id": 5})
    assert session.id == "pve3"
    assert api.paths() == [("POST", "/api/v2/matches"),
                           ("POST", "/api/v2/matches/pve3/controller")]
    assert api.calls[0]["json"] == {
        "game": "snake", "mode": "practice", "visibility": "unlisted"}
    assert api.calls[1]["json"] == {
        "seat": "p0", "controller": {"type": "model", "model_id": 5}}


def test_create_pvp_and_join_pvp(api, client):
    api.on("POST", "/api/v2/matches",
           view(id="room9", invite="XYZ", status="waiting", to_act=[]))
    api.on("POST", "/api/v2/matches/room9/seats/p1/join",
           view(id="room9", you="p1"))
    host = client.session("microrts").create_pvp(
        mode="ranked", visibility="private", seed=3)
    assert host.id == "room9" and host.invite == "XYZ"
    body = api.calls[0]["json"]
    assert body["mode"] == "ranked" and body["visibility"] == "private"
    assert body["settings"] == {"seed": 3}
    guest = client.session("microrts").join_pvp("room9", invite="XYZ")
    assert guest.id == "room9" and guest.you_seat == "p1"
    assert api.calls[1]["json"] == {"invite": "XYZ"}


def test_create_pvp_defaults_to_casual_public(api, client):
    api.on("POST", "/api/v2/matches", view(id="r1"))
    client.session("microrts").create_pvp()
    body = api.calls[0]["json"]
    assert body["mode"] == "casual" and body["visibility"] == "public"
    assert body["seats"][0]["occupant"] == "me"
    assert body["seats"][1]["occupant"] is None


def test_act_posts_tick_and_polls_until_my_turn_again(api, client):
    api.on("POST", "/api/v2/matches", view(id="m1", tick=0, to_act=["p0", "p1"]))
    api.on("POST", "/api/v2/matches/m1/actions", {"accepted": True, "seq": 9})
    api.on("GET", "/api/v2/matches/m1",
           view(id="m1", tick=0, to_act=["p0", "p1"], submitted=["p0"]),
           view(id="m1", tick=1, to_act=["p0"]))
    session = client.session("microrts").create_pvp()
    out = session.act(7, poll=0)
    assert out["tick"] == 1
    assert session.tick == 1 and session.your_turn and not session.done
    assert session.last_ack == {"accepted": True, "seq": 9}
    assert api.calls[1]["json"] == {"tick": 0, "action": 7}
    assert api.paths()[1:] == [("POST", "/api/v2/matches/m1/actions"),
                               ("GET", "/api/v2/matches/m1"),
                               ("GET", "/api/v2/matches/m1")]


def test_act_retries_after_stale_tick(api, client):
    api.on("POST", "/api/v2/matches", view(id="m1", tick=0, to_act=["p0"]))
    api.on("POST", "/api/v2/matches/m1/actions",
           PlatformError("局面已更新", code="stale_tick", status=409),
           {"accepted": True, "seq": 2})
    api.on("GET", "/api/v2/matches/m1",
           view(id="m1", tick=2, to_act=["p0"]),
           view(id="m1", tick=3, to_act=["p0"]))
    session = client.session("microrts").create_pvp()
    out = session.act(1, poll=0)
    assert out["tick"] == 3
    ticks = [c["json"]["tick"] for c in api.calls
             if c["path"] == "/api/v2/matches/m1/actions"]
    assert ticks == [0, 2]
    assert api.paths()[2:] == [
        ("GET", "/api/v2/matches/m1"),
        ("POST", "/api/v2/matches/m1/actions"),
        ("GET", "/api/v2/matches/m1")]


def test_act_waits_until_my_turn_before_posting(api, client):
    api.on("POST", "/api/v2/matches", view(id="m1", tick=1, to_act=["p0", "p1"]))
    api.on("GET", "/api/v2/matches/m1",
           view(id="m1", tick=1, to_act=["p1"], submitted=["p0"]),
           view(id="m1", tick=2, to_act=["p0"]),
           view(id="m1", tick=3, to_act=["p0"]))
    api.on("POST", "/api/v2/matches/m1/actions", {"accepted": True, "seq": 3})
    session = client.session("microrts").create_pvp()
    session.match = view(id="m1", tick=1, to_act=["p1"])
    out = session.act(4, poll=0)
    assert out["tick"] == 3
    assert [c["method"] for c in api.calls] == [
        "POST", "GET", "GET", "POST", "GET"]


def test_act_stops_on_terminal_snapshot(api, client):
    api.on("POST", "/api/v2/matches", view(id="m1", tick=0, to_act=["p0"]))
    api.on("POST", "/api/v2/matches/m1/actions", {"accepted": True, "seq": 1})
    finished = view(id="m1", status="finished", tick=1, to_act=[],
                    result={"winner": "p0", "cause": "done"})
    api.on("GET", "/api/v2/matches/m1", finished)
    session = client.session("microrts").create_pvp()
    out = session.act(0, poll=0)
    assert session.done and out["status"] == "finished"
    assert session.winner == "p0" and session.cause == "done"
    assert session.waiting_for is None
    calls = len(api.calls)
    assert session.act(0, poll=0) is session.match
    assert len(api.calls) == calls


def test_act_times_out_while_waiting_for_opponent(api, client):
    api.on("POST", "/api/v2/matches", view(id="m1", tick=0, to_act=["p0", "p1"]))
    api.on("POST", "/api/v2/matches/m1/actions", {"accepted": True, "seq": 1})
    api.on("GET", "/api/v2/matches/m1",
           lambda: view(id="m1", tick=0, to_act=["p0", "p1"],
                        submitted=["p0"]))
    session = client.session("microrts").create_pvp()
    with pytest.raises(TimeoutError):
        session.act(0, timeout=0.02, poll=0)


def test_act_rejects_unacknowledged_action(api, client):
    api.on("POST", "/api/v2/matches", view(id="m1", tick=0, to_act=["p0"]))
    api.on("POST", "/api/v2/matches/m1/actions", {"accepted": False})
    session = client.session("microrts").create_pvp()
    with pytest.raises(PlatformError) as excinfo:
        session.act(1, poll=0)
    assert excinfo.value.code == "not_accepted"


def test_poll_resign_and_replay(api, client):
    api.on("POST", "/api/v2/matches", view(id="m1", tick=0))
    api.on("GET", "/api/v2/matches/m1",
           view(id="m1", tick=4),
           view(id="m1", status="finished", tick=5,
                result={"winner": "p1", "cause": "resigned"}))
    api.on("POST", "/api/v2/matches/m1/resign",
           {"status": "finished", "result": {"winner": "p1"}})
    api.on("GET", "/api/v2/matches/m1/frames?from=0&limit=2",
           {"frames": [{"tick": 0}, {"tick": 1}], "next": None, "total": 2})
    session = client.session("microrts").create_pvp()
    assert session.poll()["tick"] == 4
    out = session.resign()
    assert out["status"] == "finished"
    assert session.done and session.winner == "p1" and session.cause == "resigned"
    replay = session.replay(limit=2)
    assert replay["total"] == 2 and len(replay["frames"]) == 2


def test_rematch_switches_to_new_match(api, client):
    api.on("POST", "/api/v2/matches", view(id="m1", tick=0))
    api.on("POST", "/api/v2/matches/m1/rematch",
           {"state": "accepted", "by": "p1", "match_id": "m2"})
    api.on("GET", "/api/v2/matches/m2", view(id="m2", tick=0, to_act=["p0"]))
    session = client.session("microrts").create_pvp()
    out = session.rematch()
    assert session.id == "m2" and out["id"] == "m2"
    assert session.last_rematch == {"state": "accepted", "by": "p1",
                                    "match_id": "m2"}


def test_rematch_offer_keeps_current_match(api, client):
    api.on("POST", "/api/v2/matches", view(id="m1", tick=0))
    api.on("POST", "/api/v2/matches/m1/rematch",
           {"state": "offered", "by": "p0", "expires_at": 123})
    api.on("GET", "/api/v2/matches/m1", view(id="m1", status="finished", tick=9))
    session = client.session("microrts").create_pvp()
    session.rematch()
    assert session.id == "m1"
    assert session.last_rematch["state"] == "offered"


def test_session_status_properties_and_set_controller(api, client):
    live = view(id="m1", tick=3, to_act=["p0", "p1"],
                seats=[{"seat": "p0", "submitted": False},
                       {"seat": "p1", "submitted": True}],
                chat=[{"id": 1, "text": "hi"}])
    api.on("POST", "/api/v2/matches", live)
    api.on("POST", "/api/v2/matches/m1/controller", view(id="m1", tick=3))
    session = client.session("microrts").create_pvp()
    assert session.status == "active" and not session.done
    assert session.you_seat == "p0" and session.tick == 3
    assert session.to_act == ["p0", "p1"]
    assert session.waiting_for == "p0"
    assert session.chat == [{"id": 1, "text": "hi"}]
    assert session.snapshot is session.match
    switched = session.set_controller({"type": "ai", "strategy": "dqn"})
    assert switched["id"] == "m1"
    assert api.calls[1]["json"] == {
        "seat": "p0", "controller": {"type": "ai", "strategy": "dqn"}}


def test_session_requires_a_match_id_for_commands(client):
    session = client.session("microrts")
    for call in (session.poll, session.replay, session.resign, session.rematch,
                 lambda: session.set_controller({"type": "human"})):
        with pytest.raises(PlatformError) as excinfo:
            call()
        assert excinfo.value.code == "no_match"


def test_act_without_a_seat_is_rejected(api, client):
    api.on("POST", "/api/v2/matches", view(id="m1", you=None))
    session = client.session("microrts").create_pvp()
    with pytest.raises(PlatformError) as excinfo:
        session.act(1, poll=0)
    assert excinfo.value.code == "not_your_seat"
