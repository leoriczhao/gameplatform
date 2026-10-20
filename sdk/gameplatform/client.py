"""Typed clients for the platform's v1 API: accounts, models, matches, play.

    from gameplatform import PlatformClient

    c = PlatformClient(base_url="https://games.cree1p.com")
    c.login("alice", "secret")                       # or c.register(...)

    model = c.upload_model("my_snake_dqn.onnx", game="snake", name="我的DQN")
    c.eval_model(model["id"])

    # 模型对战（异步）：创建后轮询直到结束
    match_id = c.create_match(game="microrts", model_a=model["id"],
                              model_b="ai:light_rush")
    result = c.wait_match(match_id)

    # 全量 API 玩（会话制，服务器权威）
    s = c.session("microrts")
    s.start_pve(opponent="worker_rush")
    while not s.done:
        s.act(build_commands(s.state))               # 你本地任意决策逻辑

    p = c.session("microrts").create_pvp()
    print("邀请码:", p.invite)                        # 发给朋友
"""
from __future__ import annotations

import time

import requests

DEFAULT_BASE_URL = "https://games.cree1p.com"


class PlatformError(RuntimeError):
    pass


class PlatformClient:
    """HTTP wrapper for /api/v1/* (auth, models, matches, ratings, play)."""

    def __init__(self, base_url: str = DEFAULT_BASE_URL, token: str | None = None,
                 timeout: float = 15.0):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.http = requests.Session()
        if token:
            self.http.headers["Authorization"] = f"Bearer {token}"

    # ------------------------------------------------------------- plumbing
    def _req(self, method: str, path: str, **kw) -> dict:
        kw.setdefault("timeout", self.timeout)
        resp = self.http.request(method, self.base_url + path, **kw)
        if not resp.ok:
            detail = f"HTTP {resp.status_code}"
            try:
                data = resp.json()
                if isinstance(data.get("detail"), str):
                    detail = data["detail"]
                elif data.get("detail"):
                    detail = str(data["detail"])
            except Exception:
                pass
            raise PlatformError(detail)
        if resp.status_code == 204:
            return {}
        return resp.json()

    # ----------------------------------------------------------------- auth
    def register(self, username: str, password: str) -> dict:
        d = self._req("POST", "/api/v1/auth/register",
                      json={"username": username, "password": password})
        self.token = d["token"]
        self.http.headers["Authorization"] = f"Bearer {d['token']}"
        return d["user"]

    def login(self, username: str, password: str) -> dict:
        d = self._req("POST", "/api/v1/auth/login",
                      json={"username": username, "password": password})
        self.token = d["token"]
        self.http.headers["Authorization"] = f"Bearer {d['token']}"
        return d["user"]

    def guest(self) -> str:
        d = self._req("POST", "/api/v1/auth/guest")
        self.token = d.get("token") or self.token
        if self.token:
            self.http.headers["Authorization"] = f"Bearer {self.token}"
        return self.token

    def me(self) -> dict:
        return self._req("GET", "/api/v1/auth/me")["user"]

    # --------------------------------------------------------------- models
    def upload_model(self, path: str, game: str, name: str) -> dict:
        with open(path, "rb") as f:
            d = self._req(
                "POST", "/api/v1/models",
                files={"file": (path.rsplit("/", 1)[-1], f,
                                "application/octet-stream")},
                data={"game": game, "name": name})
        return d["model"]

    def list_models(self, game: str | None = None) -> list[dict]:
        models = self._req("GET", "/api/v1/models")["models"]
        return [m for m in models if game is None or m["game"] == game]

    def get_model(self, model_id: int) -> dict:
        return self._req("GET", f"/api/v1/models/{model_id}")["model"]

    def delete_model(self, model_id: int) -> dict:
        return self._req("DELETE", f"/api/v1/models/{model_id}")

    def eval_model(self, model_id: int) -> dict:
        return self._req("POST", f"/api/v1/models/{model_id}/eval")["metrics"]

    # --------------------------------------------------------------- matches
    def create_match(self, game: str, model_a: int, model_b) -> int:
        """model_b: model id (int) | "ai:<strategy>" | bare strategy name."""
        if isinstance(model_b, str) and not model_b.isdigit() \
                and not model_b.startswith("ai:"):
            model_b = f"ai:{model_b}"
        return self._req("POST", "/api/v1/matches",
                         json={"game": game, "model_a": int(model_a),
                               "model_b": model_b})["match_id"]

    def get_match(self, match_id: int) -> dict:
        return self._req("GET", f"/api/v1/matches/{match_id}")["match"]

    def my_matches(self) -> list[dict]:
        return self._req("GET", "/api/v1/matches")["matches"]

    def wait_match(self, match_id: int, timeout: float = 300.0,
                   poll: float = 2.0) -> dict:
        """Poll an async match until it finishes/fails; returns the match."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            m = self.get_match(match_id)
            if m["status"] in ("finished", "failed"):
                return m
            time.sleep(poll)
        raise TimeoutError(f"match {match_id} still running after {timeout}s")

    def ratings(self, game: str) -> list[dict]:
        return self._req("GET", f"/api/v1/ratings/{game}")["items"]

    # ------------------------------------------------------- leaderboard
    def submit_score(self, game: str, match_id: int,
                     name: str | None = None) -> dict:
        """Claim a leaderboard slot from a finished PvE match. The score is
        read server-side from that match; clients cannot report a number."""
        body: dict = {"match_id": int(match_id)}
        if name:
            body["name"] = name
        return self._req("POST", f"/api/{game}/scores", json=body)

    def scores(self, game: str, limit: int = 10) -> list[dict]:
        return self._req("GET",
                         f"/api/{game}/scores?limit={int(limit)}")["items"]

    # --------------------------------------------------- social (v1.0-b)
    def profile(self) -> dict:
        return self._req("GET", "/api/v1/profile")["profile"]

    def update_profile(self, nickname: str | None = None,
                       avatar: str | None = None,
                       signature: str | None = None) -> dict:
        body = {}
        if nickname is not None:
            body["nickname"] = nickname
        if avatar is not None:
            body["avatar"] = avatar
        if signature is not None:
            body["signature"] = signature
        return self._req("PUT", "/api/v1/profile", json=body)["profile"]

    def friends(self) -> list[dict]:
        return self._req("GET", "/api/v1/friends")["friends"]

    def add_friend(self, username: str) -> dict:
        return self._req("POST", "/api/v1/friends",
                         json={"username": username})["friend"]

    def remove_friend(self, friend_id: int) -> dict:
        return self._req("DELETE", f"/api/v1/friends/{friend_id}")

    def chat_send(self, game: str, session_id: str, text: str) -> dict:
        return self._req("POST",
                         f"/api/v1/{game}/play/sessions/{session_id}/chat",
                         json={"text": text})["message"]

    def chat_since(self, game: str, session_id: str, since: int = 0) -> dict:
        return self._req("GET",
                         f"/api/v1/{game}/play/sessions/{session_id}/chat"
                         f"?since={since}")

    def notifications(self) -> dict:
        return self._req("GET", "/api/v1/notifications")

    def notifications_unread(self) -> int:
        return self._req("GET", "/api/v1/notifications/unread")["unread"]

    def notifications_read_all(self) -> dict:
        return self._req("POST", "/api/v1/notifications/read")

    # ------------------------------------------ growth/stats (v1.0-c)
    def stats_me(self) -> dict:
        """My battle record: totals, per-game breakdown, ELO history,

        XP and level (docs/design/08)."""
        return self._req("GET", "/api/v1/stats/me")

    def leaderboard(self, game: str, scope: str = "total") -> list[dict]:
        """scope: total (ELO) | weekly (last-7-days wins)."""
        return self._req("GET",
                         f"/api/v1/leaderboards/{game}?scope={scope}")["items"]

    # ----------------------------------------------------- ops (v1.0-d)
    def announcements(self) -> list[dict]:
        """Active site-wide announcements (public endpoint)."""
        return self._req("GET", "/api/v1/announcements")["items"]

    def report(self, target_type: str, target_id: int,
               reason: str = "") -> dict:
        """File a report (user|model|match|chat)."""
        return self._req("POST", "/api/v1/reports",
                         json={"target_type": target_type,
                               "target_id": target_id, "reason": reason})["report"]

    # admin console (requires an admin account)
    def admin_dashboard(self) -> dict:
        return self._req("GET", "/api/v1/admin/dashboard")

    def admin_users(self) -> list[dict]:
        return self._req("GET", "/api/v1/admin/users")["users"]

    def admin_set_user_status(self, user_id: int, status: str) -> dict:
        """Ban/unban: status active|banned."""
        return self._req("POST", f"/api/v1/admin/users/{user_id}/status",
                         json={"status": status})

    def admin_models(self) -> list[dict]:
        return self._req("GET", "/api/v1/admin/models")["models"]

    def admin_set_model_status(self, model_id: int, status: str) -> dict:
        """Model takedown/restore: status active|banned."""
        return self._req("POST", f"/api/v1/admin/models/{model_id}/status",
                         json={"status": status})

    def admin_matches(self) -> list[dict]:
        return self._req("GET", "/api/v1/admin/matches")["matches"]

    def admin_reports(self, status: str | None = None) -> list[dict]:
        path = "/api/v1/admin/reports" + (f"?status={status}" if status else "")
        return self._req("GET", path)["reports"]

    def admin_set_report_status(self, rid: int, status: str) -> dict:
        return self._req("POST", f"/api/v1/admin/reports/{rid}/status",
                         json={"status": status})

    def admin_create_announcement(self, body: str) -> dict:
        return self._req("POST", "/api/v1/admin/announcements",
                         json={"body": body})["announcement"]

    def admin_set_announcement(self, aid: int, active: bool) -> dict:
        return self._req("POST", f"/api/v1/admin/announcements/{aid}/active",
                         json={"status": "on" if active else "off"})

    def match_replay(self, match_id: int) -> dict:
        """Public replay view (06 §7 / 07 M4): players + result + seed +
        per-tick moves. Rebuild states locally via the env API (same seed
        => same trajectory)."""
        return self._req("GET", f"/api/v1/matches/{match_id}/replay")["replay"]

    # ------------------------------------------------------------------ play
    def session(self, game: str) -> "SessionClient":
        return SessionClient(self, game)

    # ------------------------------------------------------- rooms (v1.0-a)
    def create_room(self, game: str, mode: str = "casual",
                    visibility: str = "public",
                    seed: int | None = None) -> "SessionClient":
        """Create a PvP room. mode: ranked|casual (D10 default casual);
        visibility: public (lobby list) | private (invite only)."""
        payload = {"mode": mode, "visibility": visibility}
        if seed is not None:
            payload["settings"] = {"seed": seed}
        d = self._req("POST", f"/api/v1/{game}/play/rooms", json=payload)
        s = SessionClient(self, game)
        s._apply(d)
        s.invite = d.get("invite")
        return s

    def list_rooms(self, game: str, mode: str | None = None) -> list[dict]:
        """Waiting public rooms for one game (optional mode filter)."""
        path = f"/api/v1/{game}/play/rooms"
        if mode:
            path += f"?mode={mode}"
        return self._req("GET", path)["rooms"]

    def join_room(self, game: str, room_id: str,
                  invite: str | None = None) -> "SessionClient":
        """Join a waiting room by id; private rooms need the invite code."""
        body = {"invite": invite} if invite else {}
        d = self._req("POST",
                      f"/api/v1/{game}/play/rooms/{room_id}/join", json=body)
        s = SessionClient(self, game)
        s._apply(d)
        s.invite = d.get("invite")
        return s

    # ----------------------------------------------- quick match (v1.0-a M2)
    def join_quick_match(self, game: str, mode: str = "ranked",
                         timeout: float = 60.0, poll: float = 1.0) -> "SessionClient":
        """Enter the matchmaking queue and block until matched; returns a
        SessionClient attached to the matched PvP room (D9: ELO band relaxes
        over time, so two waiting players always match eventually)."""
        d = self._req("POST", f"/api/v1/{game}/matchmaking/queue",
                      json={"mode": mode})
        if d.get("matched") and d.get("session_id"):
            return self._open_matched_session(game, d["session_id"])
        deadline = time.time() + timeout
        while time.time() < deadline:
            st = self.queue_status(game)
            if st.get("matched") and st.get("session_id"):
                return self._open_matched_session(game, st["session_id"])
            if not st.get("queued"):
                raise PlatformError("已不在匹配队列中（超时或被取消）")
            time.sleep(poll)
        raise TimeoutError(f"quick match timed out after {timeout}s")

    def _open_matched_session(self, game: str, sid: str) -> "SessionClient":
        s = SessionClient(self, game)
        d = self._req("GET", f"/api/v1/{game}/play/sessions/{sid}")
        s._apply(d)
        return s

    def queue_status(self, game: str) -> dict:
        """Current matchmaking queue state (poll every ~2s)."""
        return self._req("GET", f"/api/v1/{game}/matchmaking/status")

    def cancel_queue(self, game: str) -> dict:
        """Leave the matchmaking queue."""
        return self._req("DELETE", f"/api/v1/{game}/matchmaking/queue")

    # ------------------------------------------- reconnect/rematch (v1.0-a M3)
    def active_games(self) -> list[dict]:
        """My unfinished (waiting/active) sessions with my side — the
        disconnect-reconnect entry point (06 §7 U5)."""
        return self._req("GET", "/api/v1/play/active")["sessions"]

    # ------------------------------------------------- UGC (v1.1, docs/design/10-11)
    def upload_game(self, path: str, changelog: str = "") -> dict:
        """Upload a UGC game zip (game.yaml + __init__.py) as a draft."""
        with open(path, "rb") as f:
            d = self._req(
                "POST", "/api/v1/ugc/games",
                files={"file": (path.rsplit("/", 1)[-1], f, "application/zip")},
                data={"changelog": changelog})
        return d["game"]

    def add_game_version(self, game_id: int, path: str,
                         changelog: str = "") -> dict:
        """Upload a new version of an existing game (version must increase)."""
        with open(path, "rb") as f:
            d = self._req(
                "POST", f"/api/v1/ugc/games/{game_id}/versions",
                files={"file": (path.rsplit("/", 1)[-1], f, "application/zip")},
                data={"changelog": changelog})
        return d["game"]

    def list_my_games(self) -> list[dict]:
        return self._req("GET", "/api/v1/ugc/games")["games"]

    def public_ugc_games(self) -> list[dict]:
        """Published UGC directory (status=published)."""
        return self._req("GET", "/api/v1/ugc/games?status=published")["games"]

    def submit_game(self, game_id: int) -> dict:
        """Submit a draft for review."""
        return self._req("POST", f"/api/v1/ugc/games/{game_id}/submit")["game"]

    def unpublish_game(self, game_id: int) -> dict:
        """Author self-unpublish (published -> draft)."""
        return self._req("POST", f"/api/v1/ugc/games/{game_id}/unpublish")["game"]

    def delete_game(self, game_id: int) -> dict:
        """Delete a draft only."""
        return self._req("DELETE", f"/api/v1/ugc/games/{game_id}")

    def smoke_test_game(self, game_id: int) -> dict:
        """Re-run the sandbox smoke test for a game (author self-check)."""
        return self._req("POST", f"/api/v1/ugc/games/{game_id}/test")

    # admin UGC review
    def admin_ugc_queue(self) -> list[dict]:
        return self._req("GET", "/api/v1/admin/ugc")["games"]

    def admin_ugc_approve(self, game_id: int) -> dict:
        return self._req("POST", f"/api/v1/admin/ugc/{game_id}/approve")["game"]

    def admin_ugc_reject(self, game_id: int, note: str) -> dict:
        return self._req("POST", f"/api/v1/admin/ugc/{game_id}/reject",
                         json={"note": note})["game"]

    def admin_ugc_ban(self, game_id: int) -> dict:
        return self._req("POST", f"/api/v1/admin/ugc/{game_id}/ban")["game"]

    def admin_ugc_unban(self, game_id: int) -> dict:
        return self._req("POST", f"/api/v1/admin/ugc/{game_id}/unban")["game"]



class SessionClient:
    """One server-side authoritative play session (PvE or PvP).

    After every call the authoritative `state` is refreshed; for PvP call
    `poll()` to observe the opponent's submission / tick advances.
    """

    def __init__(self, client: PlatformClient, game: str):
        self.client = client
        self.game = game
        self.session: dict | None = None
        self.side: str = "p0"
        self.invite: str | None = None
        self.last_response: dict = {}

    # ------------------------------------------------------------- lifecycle
    def _apply(self, d: dict) -> dict:
        self.session = d["session"]
        if "state" in self.session:
            self.state = self.session["state"]
        self.side = d.get("side") or self.session.get("side") or "p0"
        self.invite = d.get("invite") or self.session.get("invite")
        return self.session

    def start_pve(self, opponent=None, controller=None, seed: int | None = None):
        """opponent: None | "strategy" | {"type":"ai","strategy":…} |
        {"type":"model","model_id":N} | {"type":"external_bot","url":…}
        controller: {"type":"model","model_id":N} (server autopilot)."""
        if isinstance(opponent, str):
            opponent = {"type": "ai", "strategy": opponent}
        payload = {"kind": "pve", "seed": seed}
        if opponent:
            payload["opponent"] = opponent
        if controller:
            payload["controller"] = controller
        self._apply(self.client._req(
            "POST", f"/api/v1/{self.game}/play/sessions", json=payload))
        return self

    def create_pvp(self, seed: int | None = None, mode: str | None = None,
                   visibility: str | None = None):
        """Legacy invite-code flow; bare params stay ranked/private for
        backward compatibility (06 §4.2)."""
        payload = {"kind": "pvp", "seed": seed}
        if mode:
            payload["mode"] = mode
        if visibility:
            payload["visibility"] = visibility
        d = self.client._req("POST", f"/api/v1/{self.game}/play/sessions",
                             json=payload)
        self._apply(d)
        self.invite = d.get("invite")
        return self

    def join_pvp(self, invite: str):
        self._apply(self.client._req(
            "POST", f"/api/v1/{self.game}/play/sessions",
            json={"kind": "pvp", "invite": invite.strip().upper()}))
        return self

    # ---------------------------------------------------------------- play
    def act(self, actions, autopoll: bool = True) -> dict:
        """Submit this side's commands for one tick (None for autopilot).
        Sends the observed tick for optimistic concurrency (409 = re-poll)."""
        d = self.client._req(
            "POST", f"/api/v1/{self.game}/play/sessions/{self.session['id']}/actions",
            json={"actions": actions, "expected_tick": self.tick})
        self.last_response = d
        if "state" in d:
            self.state = d["state"]
        if d.get("status"):
            self.session["status"] = d["status"]
            if d.get("done"):
                self.session["winner"] = d.get("winner")
                self.session["cause"] = d.get("cause")
        if autopoll and self.session["kind"] == "pvp":
            self.poll()
        return d

    def poll(self) -> dict:
        d = self.client._req(
            "GET", f"/api/v1/{self.game}/play/sessions/{self.session['id']}")
        self._apply(d)
        return self.session

    def resign(self) -> dict:
        d = self.client._req(
            "POST", f"/api/v1/{self.game}/play/sessions/{self.session['id']}/leave")
        self.poll()
        return d

    def rematch(self):
        """再来一局（06 §7 U7）：新房间复制 settings/mode/visibility，
        p0/p1 互换，双方自动回到新对局；对已 rematch 过的房间幂等。"""
        d = self.client._req(
            "POST",
            f"/api/v1/{self.game}/play/sessions/{self.session['id']}/rematch")
        self._apply(d)
        self.invite = d.get("invite")
        return self

    def replay(self) -> dict:
        return self.client._req(
            "GET", f"/api/v1/{self.game}/play/sessions/{self.session['id']}/replay")

    # ------------------------------------------------------------- status
    @property
    def status(self) -> str:
        return self.session["status"] if self.session else ""

    @property
    def done(self) -> bool:
        return bool(self.session and self.session["status"] == "finished")

    @property
    def winner(self):
        return self.session.get("winner") if self.session else None

    @property
    def cause(self):
        return self.session.get("cause") if self.session else None

    @property
    def tick(self) -> int:
        return int(self.state.get("tick", 0)) if self.state is not None else 0

    @property
    def waiting_for(self) -> str | None:
        return self.last_response.get("waiting_for")
