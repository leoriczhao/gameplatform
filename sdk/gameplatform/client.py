"""Typed clients for the platform API: accounts, models and v2 matches.

The match protocol is **v2** (design 17 §5): commands over REST, snapshots from
GET /api/v2/matches/{uid} and history from the frames endpoint. The v1 session
/ room / quick-match APIs no longer exist (SDK 1.0 breaking release).

    from gameplatform import PlatformClient

    c = PlatformClient(base_url="https://games.cree1p.com")
    c.login("alice", "secret")                       # or c.register(...)

    model = c.upload_model("my_snake_dqn.onnx", game="snake", name="我的DQN")
    c.eval_model(model["id"])

    # 模型对战（v2，两个 model 座位）：返回对局 uid，轮询快照直到终局
    uid = c.create_match(game="microrts", model_a=model["id"],
                         model_b="ai:light_rush")
    result = c.wait_match(uid)

    # 全量 API 玩（v2 对局客户端，服务器权威）
    s = c.session("microrts")
    s.start_pve(opponent="worker_rush")
    while not s.done:
        s.act(build_commands(s.match))               # 你本地任意决策逻辑

    p = c.session("microrts").create_pvp()
    print("对局 id:", p.id, "邀请码:", p.invite)       # 发给朋友
"""
from __future__ import annotations

import time
from urllib.parse import quote

import requests

DEFAULT_BASE_URL = "https://games.cree1p.com"

#: Match statuses after which no command is accepted (design 17 §5).
TERMINAL_STATUS = ("finished", "cancelled", "aborted")


class PlatformError(RuntimeError):
    """An API error carrying the platform's machine-readable error code.

    v2 errors are {code, message} (design 17 §5.1): e.g. stale_tick,
    not_to_act, match_over.
    """

    def __init__(self, message: str, *, code: str | None = None,
                 status: int | None = None, detail=None):
        super().__init__(message)
        self.code = code
        self.status = status
        self.detail = detail


def _controller(value) -> dict:
    """Normalise a seat controller spec to the v2 shape.

    Accepts a controller dict as-is, a model id, "ai:<strategy>" or a bare
    strategy name (design 17 §5: {"type": "human"|"ai"|"model"|"bot", ...}).
    """
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, int):
        return {"type": "model", "model_id": value}
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit():
            return {"type": "model", "model_id": int(text)}
        if text.startswith("ai:"):
            text = text[3:]
        return {"type": "ai", "strategy": text}
    raise TypeError(f"无法识别的 controller：{value!r}")


class PlatformClient:
    """HTTP wrapper for the platform API: auth, models, v2 matches, ratings."""

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
            status = resp.status_code
            code = None
            message = f"HTTP {status}"
            try:
                data = resp.json()
            except Exception:
                data = None
            if isinstance(data, dict):
                err = data.get("detail", data)
                if isinstance(err, dict):
                    code = err.get("code")
                    if isinstance(err.get("message"), str):
                        message = err["message"]
                    elif err.get("message") is not None:
                        message = str(err["message"])
                elif isinstance(err, str):
                    message = err
            raise PlatformError(message, code=code, status=status, detail=data)
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

    # ----------------------------------------------------------- matches (v2)
    def create_match(self, game: str, model_a: int, model_b) -> str:
        """Create a v2 model-vs-model match; returns the match uid.

        Seats: p0 = model_a (a model of yours), p1 = model_b -- a model id,
        "ai:<strategy>" or a bare strategy name (a controller dict passes
        through). kind/mode are derived by the server (design 17 §5).
        """
        seats = [
            {"seat": "p0", "occupant": None,
             "controller": {"type": "model", "model_id": int(model_a)}},
            {"seat": "p1", "occupant": None, "controller": _controller(model_b)},
        ]
        view = self._req("POST", "/api/v2/matches",
                         json={"game": game, "seats": seats})
        return view["id"]

    def get_match(self, uid: str) -> dict:
        """The v2 MatchView snapshot (design 17 §5)."""
        return self._req("GET", f"/api/v2/matches/{uid}")

    def wait_match(self, uid: str, timeout: float = 300.0,
                   poll: float = 2.0) -> dict:
        """Poll the v2 snapshot until the match is terminal; returns it."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            view = self.get_match(uid)
            if view.get("status") in TERMINAL_STATUS:
                return view
            time.sleep(poll)
        raise TimeoutError(f"match {uid} still running after {timeout}s")

    def match_replay(self, uid: str, *, limit: int = 500) -> dict:
        """Assemble the full frame history via /frames pagination.

        Returns {"id": uid, "frames": [{tick, frame, actions, events}],
        "total": n}. States come from the sealed frames; the client never
        re-simulates the match.
        """
        page_size = max(1, min(int(limit), 500))   # the server caps frames pages at 500
        frames: list[dict] = []
        offset, total = 0, None
        while True:
            page = self._req(
                "GET",
                f"/api/v2/matches/{uid}/frames?from={offset}&limit={page_size}")
            items = page.get("frames") or []
            frames.extend(items)
            total = page.get("total", total)
            nxt = page.get("next")
            if nxt is None or not items or int(nxt) <= offset:
                break
            offset = int(nxt)
        return {"id": uid, "frames": frames,
                "total": len(frames) if total is None else int(total)}

    def my_matches(self) -> list[dict]:
        """v1 match history list (GET /api/v1/matches, kept read-only).

        Historical records only. For live/reconnect matches use
        my_live_matches() (v2 MatchView snapshots).
        """
        return self._req("GET", "/api/v1/matches")["matches"]

    def my_live_matches(self) -> list[dict]:
        """My waiting/active v2 matches -- the reconnect entry point."""
        return self._req("GET", "/api/v2/me/matches")["matches"]

    def ratings(self, game: str) -> list[dict]:
        return self._req("GET", f"/api/v1/ratings/{game}")["items"]

    # ------------------------------------------------------- leaderboard
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

    def send_chat(self, uid: str, text: str) -> dict:
        """Send room chat (players only); returns the stored message.

        Reads come from MatchView["chat"] (snapshot) or the stream's chat
        event -- the v2 protocol has no chat polling endpoint.
        """
        return self._req("POST", f"/api/v2/matches/{uid}/chat",
                         json={"text": text})["message"]

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

    # ------------------------------------------------------------ v2 session
    def session(self, game: str, match_id: str | None = None) -> "SessionClient":
        """A stateful v2 match client; pass match_id to attach to one."""
        return SessionClient(self, game, match_id)

    # ------------------------------------------------------- rooms (design 17)
    def create_room(self, game: str, mode: str = "casual",
                    visibility: str = "public",
                    seed: int | None = None) -> dict:
        """Create a v2 PvP room (p0 = me, p1 open); returns its MatchView.

        mode: ranked|casual. visibility: public (lobby) | unlisted | private
        (view["invite"] is required to join). Hosting it through a
        SessionClient is the c.session(game).create_pvp() path.
        """
        seats = [
            {"seat": "p0", "occupant": "me", "controller": {"type": "human"}},
            {"seat": "p1", "occupant": None, "controller": {"type": "human"}},
        ]
        body: dict = {"game": game, "seats": seats,
                      "mode": mode, "visibility": visibility}
        if seed is not None:
            body["settings"] = {"seed": int(seed)}
        return self._req("POST", "/api/v2/matches", json=body)

    def join_room(self, uid: str, invite: str | None = None,
                  seat: str = "p1") -> dict:
        """Take the open seat of a v2 room; private rooms need the invite code."""
        return self._req(
            "POST", f"/api/v2/matches/{uid}/seats/{seat}/join",
            json={"invite": invite})

    def lobby(self, game: str, mode: str | None = None) -> list[dict]:
        """Waiting public rooms for one game (v2 lobby)."""
        path = f"/api/v2/matches?game={quote(game)}"
        if mode:
            path += f"&mode={quote(mode)}"
        return self._req("GET", path)["rooms"]

    # --------------------------------------------------- v2 quick match (D9)
    def quick_match(self, game: str, mode: str = "casual",
                    timeout: float = 60.0, poll: float = 1.0) -> str:
        """Enter v2 matchmaking and block until matched; returns the match uid.

        Polls GET /api/v2/{game}/matchmaking/status until the server reports
        a match_id (the v2 matched entry is idempotent and stays readable).
        """
        st = self._req("POST", f"/api/v2/{game}/matchmaking/queue",
                       json={"mode": mode})
        deadline = time.time() + timeout
        while True:
            if st.get("match_id"):
                return st["match_id"]
            if not st.get("queued"):
                raise PlatformError("已不在匹配队列中（超时或被取消）",
                                    code="not_queued")
            if time.time() >= deadline:
                raise TimeoutError(f"quick match timed out after {timeout}s")
            time.sleep(poll)
            st = self.queue_status(game)

    def queue_status(self, game: str) -> dict:
        """v2 queue state; poll every ~2s until match_id appears."""
        return self._req("GET", f"/api/v2/{game}/matchmaking/status")

    def cancel_queue(self, game: str) -> dict:
        """Leave the v2 matchmaking queue."""
        return self._req("DELETE", f"/api/v2/{game}/matchmaking/queue")

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
    """One v2 match as a stateful client (breaking change from SDK 0.x).

    In 0.x this wrapped a v1 play session. In 1.0 it is a thin client over
    /api/v2/matches/{uid} (design 17 §5): self.match always holds the latest
    MatchView snapshot; act() submits {tick, action} and blocks until it is
    your turn again (or the match reaches a terminal status).
    """

    TERMINAL = TERMINAL_STATUS

    def __init__(self, client: "PlatformClient", game: str,
                 match_id: str | None = None, view: dict | None = None):
        self.client = client
        self.game = game
        self.id = match_id
        self.match: dict | None = None
        self.invite: str | None = None
        self.last_ack: dict = {}
        self.last_rematch: dict | None = None
        self.poll_interval = 0.25
        self.act_timeout = 120.0
        if view is not None:
            self._apply(view)

    def __repr__(self) -> str:
        return (f"<SessionClient game={self.game!r} id={self.id!r} "
                f"status={self.status!r}>")

    # ------------------------------------------------------------- plumbing
    def _apply(self, view: dict) -> dict:
        self.match = view
        self.id = view.get("id") or self.id
        self.invite = view.get("invite") or self.invite
        self.game = view.get("game") or self.game
        return view

    def _create(self, body: dict) -> "SessionClient":
        self._apply(self.client._req("POST", "/api/v2/matches", json=body))
        return self

    def _require_id(self) -> str:
        if not self.id:
            raise PlatformError("尚未创建或加入对局", code="no_match")
        return self.id

    # ------------------------------------------------------------ lifecycle
    def start_pve(self, opponent=None, controller=None,
                  seed: int | None = None) -> "SessionClient":
        """Create a practice match (mode practice, visibility unlisted).

        opponent: None keeps the game's default seating (a 1-seat game, or a
        2-seat game's default AI); otherwise the opponent for seat p1 -- an AI
        strategy ("worker_rush" / "ai:worker_rush"), a model id or a controller
        dict (2-seat games only).
        controller: controller for *your* seat, e.g.
        {"type": "model", "model_id": N} to let a model play for you.
        seed: reproducible game seed (settings.seed).
        """
        body: dict = {"game": self.game, "mode": "practice",
                      "visibility": "unlisted"}
        if seed is not None:
            body["settings"] = {"seed": int(seed)}
        if opponent is not None:
            body["seats"] = [
                {"seat": "p0", "occupant": "me",
                 "controller": _controller(controller)
                 if controller is not None else {"type": "human"}},
                {"seat": "p1", "occupant": None,
                 "controller": _controller(opponent)},
            ]
            return self._create(body)
        self._create(body)
        if controller is not None:
            # The default seat layout is server-derived; switch my seat's
            # controller afterwards (v2 /controller command, design 17 §5).
            self.set_controller(controller)
        return self

    def create_pvp(self, seed: int | None = None, mode: str | None = None,
                   visibility: str | None = None) -> "SessionClient":
        """Create a PvP room: p0 = me, p1 open (defaults casual/public, D10).

        mode: ranked|casual. visibility: public|unlisted|private (private
        rooms expose self.invite for the friend to join with).
        """
        seats = [
            {"seat": "p0", "occupant": "me", "controller": {"type": "human"}},
            {"seat": "p1", "occupant": None, "controller": {"type": "human"}},
        ]
        body: dict = {"game": self.game, "seats": seats,
                      "mode": mode or "casual",
                      "visibility": visibility or "public"}
        if seed is not None:
            body["settings"] = {"seed": int(seed)}
        return self._create(body)

    def join_pvp(self, match_id: str, invite: str | None = None,
                 seat: str = "p1") -> "SessionClient":
        """Take the open seat of a PvP room.

        v2 addresses rooms by match id (POST /api/v2/matches/{uid}/seats/{seat}
        /join); the v1 join-by-invite-only flow is gone. invite is only needed
        when the room visibility is private.
        """
        self._apply(self.client._req(
            "POST", f"/api/v2/matches/{match_id}/seats/{seat}/join",
            json={"invite": invite}))
        return self

    # --------------------------------------------------------------- reading
    def poll(self) -> dict:
        """Refresh and return the latest MatchView snapshot."""
        return self._apply(self.client._req(
            "GET", f"/api/v2/matches/{self._require_id()}"))

    def replay(self, *, limit: int = 500) -> dict:
        """Sealed frame history {"id", "frames", "total"} (/frames pages)."""
        return self.client.match_replay(self._require_id(), limit=limit)

    # ------------------------------------------------------------------ play
    def act(self, actions, *, timeout: float | None = None,
            poll: float | None = None) -> dict:
        """Submit this tick's action and wait until it is my turn again.

        The tick of the last snapshot is the idempotency key (design 17 §5.1);
        a 409 stale_tick refreshes the snapshot and retries. After the 202 ack
        this polls GET /api/v2/matches/{uid} until you.seat is in to_act again
        (and not yet submitted) or the match is terminal. Returns the MatchView.
        """
        if self.match is None:
            self.poll()
        if self.done:
            return self.match
        if not self.you_seat:
            raise PlatformError("当前账号不是本局玩家（无座位）",
                                code="not_your_seat")
        timeout = self.act_timeout if timeout is None else timeout
        wait = self.poll_interval if poll is None else poll
        deadline = time.monotonic() + timeout
        retries = 0
        while True:
            if self.done:
                return self.match
            if not self._my_turn():
                self._wait_turn(deadline, wait)
                if self.done:
                    return self.match
            try:
                ack = self.client._req(
                    "POST", f"/api/v2/matches/{self.id}/actions",
                    json={"tick": int(self.match["tick"]), "action": actions})
            except PlatformError as exc:
                if exc.code == "stale_tick" and retries < 3:
                    retries += 1
                    self.poll()
                    continue
                if exc.code == "not_to_act" and time.monotonic() < deadline:
                    if wait:
                        time.sleep(wait)
                    self.poll()
                    continue
                raise
            if not isinstance(ack, dict) or not ack.get("accepted"):
                raise PlatformError(f"动作未被接受：{ack!r}",
                                    code="not_accepted", detail=ack)
            self.last_ack = ack
            return self._wait_turn(deadline, wait, refresh_first=True)

    def _my_turn(self) -> bool:
        """True when this snapshot lets me submit (to_act, not yet submitted)."""
        view = self.match or {}
        me = (view.get("you") or {}).get("seat")
        if not me or me not in (view.get("to_act") or []):
            return False
        seat = next((s for s in view.get("seats") or []
                     if s.get("seat") == me), None)
        return not (seat or {}).get("submitted", False)

    def _wait_turn(self, deadline: float, poll: float,
                   *, refresh_first: bool = False) -> dict:
        """Poll until it is my turn again or the match is terminal."""
        if refresh_first:
            if poll:
                time.sleep(poll)
            self.poll()
        while True:
            if self.done or self._my_turn():
                return self.match
            if time.monotonic() >= deadline:
                raise TimeoutError(f"match {self.id}: 等待轮到自己超时")
            if poll:
                time.sleep(poll)
            self.poll()

    # -------------------------------------------------------------- commands
    def set_controller(self, controller, seat: str | None = None) -> dict:
        """Switch a seat's controller (practice matches only).

        E.g. hand your seat to a model: {"type": "model", "model_id": N}.
        Returns the refreshed MatchView.
        """
        match_id = self._require_id()
        seat = seat or self.you_seat
        if not seat:
            raise PlatformError("无法确定座位", code="no_seat")
        self._apply(self.client._req(
            "POST", f"/api/v2/matches/{match_id}/controller",
            json={"seat": seat, "controller": _controller(controller)}))
        return self.match

    def resign(self) -> dict:
        """Resign, or cancel the room while it is still waiting."""
        self.client._req(
            "POST", f"/api/v2/matches/{self._require_id()}/resign")
        return self.poll()

    def rematch(self) -> dict:
        """Offer (first call) or accept (other player) a rematch.

        The accepted reply carries the new match id; this client then switches
        to it. Returns the refreshed MatchView.
        """
        data = self.client._req(
            "POST", f"/api/v2/matches/{self._require_id()}/rematch")
        self.last_rematch = data
        if data.get("match_id"):
            self.id = data["match_id"]
            self.invite = None
        return self.poll()

    # ---------------------------------------------------------------- status
    @property
    def snapshot(self) -> dict | None:
        """The latest MatchView (None until created/joined/polled)."""
        return self.match

    @property
    def status(self) -> str:
        return (self.match or {}).get("status") or ""

    @property
    def done(self) -> bool:
        """True for the terminal statuses finished/cancelled/aborted."""
        return self.status in TERMINAL_STATUS

    @property
    def winner(self):
        """result.winner: a seat ("p0"/"p1") or None for a draw."""
        return ((self.match or {}).get("result") or {}).get("winner")

    @property
    def cause(self):
        return ((self.match or {}).get("result") or {}).get("cause")

    @property
    def tick(self) -> int:
        return int((self.match or {}).get("tick") or 0)

    @property
    def you_seat(self) -> str | None:
        return ((self.match or {}).get("you") or {}).get("seat")

    @property
    def your_turn(self) -> bool:
        return not self.done and self._my_turn()

    @property
    def to_act(self) -> list[str]:
        return list((self.match or {}).get("to_act") or [])

    @property
    def waiting_for(self) -> str | None:
        """First seat the match is still waiting on (None once it ends)."""
        if self.done:
            return None
        view = self.match or {}
        for seat in view.get("to_act") or []:
            row = next((s for s in view.get("seats") or []
                        if s.get("seat") == seat), None)
            if not (row or {}).get("submitted", False):
                return seat
        return None

    @property
    def chat(self) -> list[dict]:
        """Room chat from the latest snapshot (players only)."""
        return list((self.match or {}).get("chat") or [])
