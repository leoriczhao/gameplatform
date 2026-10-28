"""Match event stream (design 17 §5.2) over a real HTTP server: snapshot first,
results arrive as events, Last-Event-ID resumes, presence follows connections."""
import json
import socket
import threading
import time
from urllib.parse import urlparse

import pytest
import requests

from live_server import live_server


@pytest.fixture(scope="module")
def base():
    with live_server() as url:
        yield url


def _user(base, name):
    r = requests.post(base + "/api/v1/auth/register",
                      json={"username": name, "password": "password123"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


class Stream:
    """Reads SSE events on a background thread."""

    def __init__(self, url, headers=None):
        self.events, self._resp = [], requests.get(url, headers=headers or {}, stream=True,
                                                   timeout=(5, 30))
        assert self._resp.status_code == 200, self._resp.text
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        current = {}
        try:
            # chunk_size=1: small events must not wait in a client-side buffer
            for line in self._resp.iter_lines(chunk_size=1, decode_unicode=True):
                if line.startswith("event:"):
                    current["type"] = line[6:].strip()
                elif line.startswith("data:"):
                    current["data"] = json.loads(line[5:])
                elif line == "" and current:
                    self.events.append(current)
                    current = {}
        except Exception:
            pass

    def wait(self, pred, timeout=5.0):
        end = time.time() + timeout
        while time.time() < end:
            hit = [e for e in self.events if pred(e)]
            if hit:
                return hit[0]
            time.sleep(0.02)
        raise AssertionError(f"no matching event in {[e['type'] for e in self.events]}")

    def close(self):
        # Response.close() would wait for the next server write; drop the socket.
        sock = getattr(getattr(self._resp.raw, "connection", None), "sock", None)
        if sock is not None:
            sock.shutdown(socket.SHUT_RDWR)
        self._resp.close()


def _raw_stream(url, headers):
    """A stream on a plain socket, so closing it really drops the connection."""
    u = urlparse(url)
    sock = socket.create_connection((u.hostname, u.port), timeout=10)
    lines = "".join(f"{k}: {v}\r\n" for k, v in headers.items())
    sock.sendall(f"GET {u.path} HTTP/1.1\r\nHost: {u.netloc}\r\n{lines}\r\n".encode())
    data = b""
    while b"event: snapshot" not in data:
        data += sock.recv(65536)
    return sock


def test_snapshot_then_events_then_resume(base):
    me = _user(base, "streamer1")
    m = requests.post(base + "/api/v2/matches", json={"game": "snake"}, headers=me).json()
    url = f"{base}/api/v2/matches/{m['id']}/stream"
    s = Stream(url, me)
    snap = s.wait(lambda e: e["type"] == "snapshot")["data"]
    assert snap["status"] == "active" and snap["you"]["seat"] == "p0" and snap["tick"] == 0

    assert requests.post(f"{base}/api/v2/matches/{m['id']}/actions",
                         json={"tick": 0, "action": 1}, headers=me).status_code == 202
    sub = s.wait(lambda e: e["type"] == "submitted")["data"]
    tick = s.wait(lambda e: e["type"] == "tick")["data"]
    assert sub == {**sub, "seat": "p0", "tick": 0}
    assert tick["tick"] == 1 and tick["actions"] == {"p0": 1} and tick["to_act"] == ["p0"]
    assert tick["seq"] > sub["seq"] > snap["seq"]
    s.close()

    # resume after the snapshot: the missed events are replayed, no new snapshot
    again = Stream(url, {**me, "Last-Event-ID": str(snap["seq"])})
    again.wait(lambda e: e["type"] == "tick")
    assert [e["type"] for e in again.events][:2] == ["submitted", "tick"]
    again.close()

    # unlisted practice match: anyone with the link can watch, as a spectator
    watcher = Stream(url)
    assert watcher.wait(lambda e: e["type"] == "snapshot")["data"]["you"]["seat"] is None
    watcher.close()


def test_presence_follows_the_players_connection(base):
    a, b = _user(base, "presence_a"), _user(base, "presence_b")
    room = requests.post(base + "/api/v2/matches", headers=a, json={"game": "microrts", "seats": [
        {"seat": "p0", "occupant": "me", "controller": {"type": "human"}},
        {"seat": "p1", "occupant": None, "controller": {"type": "human"}}]}).json()
    mid = room["id"]
    requests.post(f"{base}/api/v2/matches/{mid}/seats/p1/join", json={}, headers=b)
    watch = Stream(f"{base}/api/v2/matches/{mid}/stream", a)
    watch.wait(lambda e: e["type"] == "snapshot")

    def presence():
        return [s["presence"] for s in requests.get(f"{base}/api/v2/matches/{mid}",
                                                    headers=a).json()["seats"]]
    assert presence()[0] == "online" and presence()[1] == "offline"
    b_sock = _raw_stream(f"{base}/api/v2/matches/{mid}/stream", b)
    watch.wait(lambda e: e["type"] == "seat" and e["data"]["seat"] == "p1"
               and e["data"]["presence"] == "online")
    b_sock.close()
    watch.wait(lambda e: e["type"] == "seat" and e["data"]["seat"] == "p1"
               and e["data"]["presence"] == "offline", timeout=40)
    assert presence() == ["online", "offline"]
    watch.close()
