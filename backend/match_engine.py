"""Match actor (docs/design/17 §3–§5, M1; L2 in docs/design/19).

One Match = an authoritative frame timeline + seats + a clock. PvE, PvP rooms,
autopilot, spectating, replay and model-vs-model are all the same object:

    seat controller   human | ai{strategy} | model{model_id} | bot{url}
    seat occupant     the user sitting there (None = open seat or server seat)

Every mutation of a match runs under that match's lock, so commands apply one
at a time. One scheduler thread fires move deadlines and drives
server-controlled seats, so a match advances whether or not anyone polls or is
connected; reads never mutate. Results settle in exactly one place
(``_finish``): record → ELO → ``match_finished`` event → sealed frames.

Viewers follow the per-match event log (SSE) and the frames API. Only the
turn clock exists for now (realtime is deferred, design 17 §0.1).
"""
from __future__ import annotations

import heapq
import itertools
import logging
import random
import secrets
import string
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor

import httpx

from gamekernel.views import strip_private

import events
import inference
import matches as store
import models as model_store
import registry

log = logging.getLogger(__name__)

SEATS = ("p0", "p1")
TERMINAL = ("finished", "cancelled", "aborted")
# Human-vs-human time control for packages whose game.yaml declares no clock.
PVP_MOVE_TIMEOUT_S = 60.0
PVP_MAX_TIMEOUTS = 5
VIEW_CACHE_TICKS = 4      # per-seat views kept for recent ticks (view-hook games)
AUTOPLAY_PACE_S = 0.25    # server seat of a human occupant (autopilot): watchable
BURST_TICKS = 50          # all-server matches: ticks per scheduler turn (fairness)
TICK_CAP = 5000           # engines that never finish end in a draw here
WAITING_TTL = 30 * 60     # open rooms nobody joins are cancelled
IDLE_TTL = 30 * 60        # untimed matches nobody moves in are aborted
RETAIN_S = 10 * 60        # terminal matches stay live for viewers and rematch
REMATCH_TTL = 60.0
EVENT_KEEP = 2000
MAX_LIVE_PER_USER = 8
BOT_TIMEOUT_S = 2.5


class MatchError(Exception):
    """A rejected command: HTTP status + machine-readable code (design 17 §5.1)."""

    def __init__(self, status: int, code: str, message: str, **extra):
        super().__init__(message)
        self.status, self.code, self.message, self.extra = status, code, message, extra

    def detail(self) -> dict:
        return {"code": self.code, "message": self.message, **self.extra}


def _now_ms() -> int:
    return int(time.time() * 1000)


def _name(principal: dict) -> str:
    return principal.get("nickname") or principal.get("username") or f"user-{principal['id']}"


# ------------------------------------------------------------------ event log

class EventLog:
    """Append-only, seq-numbered events of one match. Appends happen under the
    match lock; async SSE readers are woken through their own event loop."""

    def __init__(self):
        self.seq = 0
        self._items: deque[dict] = deque(maxlen=EVENT_KEEP)
        self._listeners: set = set()
        self._lock = threading.Lock()

    def append(self, type_: str, **data) -> int:
        with self._lock:
            self.seq += 1
            self._items.append({"seq": self.seq, "type": type_,
                                "server_time": _now_ms(), **data})
            listeners = list(self._listeners)
        for loop, flag in listeners:
            try:
                loop.call_soon_threadsafe(flag.set)
            except RuntimeError:
                pass  # that reader's loop is gone
        return self.seq

    def since(self, seq: int) -> list[dict] | None:
        """Events after ``seq``; None when the gap is no longer retained."""
        with self._lock:
            if seq > self.seq or seq < 0:
                return None
            if self._items and self._items[0]["seq"] > seq + 1:
                return None
            return [e for e in self._items if e["seq"] > seq]

    def listen(self, loop, flag) -> None:
        with self._lock:
            self._listeners.add((loop, flag))

    def unlisten(self, loop, flag) -> None:
        with self._lock:
            self._listeners.discard((loop, flag))


# ------------------------------------------------------------------ seats

class Seat:
    def __init__(self, seat: str, occupant: dict | None, controller: dict):
        self.seat = seat
        self.occupant = occupant          # {"user_id", "name"} | None
        self.controller = controller      # {"type": "human"|"ai"|"model"|"bot", ...}
        self.timeouts = 0
        self._model_session = None

    @property
    def human(self) -> bool:
        return self.controller["type"] == "human"

    @property
    def open(self) -> bool:
        return self.human and self.occupant is None

    def public_controller(self) -> dict:
        c = {"type": self.controller["type"]}
        for key in ("strategy", "model_id", "name"):
            if key in self.controller:
                c[key] = self.controller[key]
        return c  # a bot's URL stays private


# ------------------------------------------------------------------ match

class Match:
    def __init__(self, *, game: str, adapter, seats: list[Seat], kind: str, mode: str,
                 visibility: str, creator_id: int | None, seed: int, clock: dict,
                 seeded: bool = False):
        self.uid = secrets.token_hex(6)
        self.game = game
        self.adapter = adapter
        self.meta = getattr(adapter, "meta", None) or {}
        self.version = self.meta.get("version")
        self.seats = {s.seat: s for s in seats}
        self.kind, self.mode, self.visibility = kind, mode, visibility
        self.invite = _invite_code() if visibility == "private" else None
        self.creator_id = creator_id
        self.seed = seed
        self.seeded = seeded   # a chosen seed is reproducible, so it never ranks
        self.clock = clock
        self.options = getattr(adapter, "pvp_options", None) if len(seats) == 2 else None
        self.empty_action = getattr(adapter, "pvp_empty_action", [])
        self.status = "waiting"
        self.steps = 0   # resolved ticks; the tick when the state carries none
        self.state = adapter.new_state(seed, self.options) if self.options is not None \
            else adapter.new_state(seed)
        self.frames = [{"tick": self.tick, "frame": self.state, "actions": None,
                        "events": self.state.get("events", [])}]
        self.to_act: list[str] = []
        self.pending: dict = {}
        self.deadline_at: float | None = None
        self.result: dict | None = None
        self.rematch: dict | None = None
        self.assisted = any(s.occupant and not s.human for s in seats)
        self.created_at = self.updated_at = time.time()
        self.finished_at: float | None = None
        self.row_id: int | None = None
        self.presence: dict[int, int] = {}
        self._views: dict[tuple[int, str | None], dict] = {}
        self.viewers = 0
        self.lock = threading.RLock()
        self.log = EventLog()

    # ------------------------------------------------------------- reads
    @property
    def tick(self) -> int:
        return int(self.state.get("tick", self.steps))

    def seat_of(self, user_id) -> str | None:
        if user_id is None:
            return None
        for s in self.seats.values():
            if s.occupant and s.occupant["user_id"] == user_id:
                return s.seat
        return None

    def _presence(self, s: Seat) -> str:
        if not s.human:
            return "server"
        if s.occupant is None:
            return "empty"
        return "online" if self.presence.get(s.occupant["user_id"]) else "offline"

    def frame_for(self, frame: dict, tick: int, seat: str | None) -> dict:
        """The viewer's share of a state: private ("_") keys and whatever the
        package's view hook hides stay on the server until the match ends."""
        if self.status in TERMINAL or frame is None:
            return frame
        if "view" not in (getattr(self.adapter, "hooks", None) or ()):
            return strip_private(frame)
        key = (tick, seat)
        if key not in self._views:
            if len(self._views) > VIEW_CACHE_TICKS * (len(self.seats) + 1):
                horizon = self.tick - VIEW_CACHE_TICKS
                self._views = {k: v for k, v in self._views.items() if k[0] > horizon}
            self._views[key] = self.adapter.view(frame, seat)
        return self._views[key]

    def frames_for(self, start: int, limit: int, user_id=None) -> tuple[list[dict], int]:
        with self.lock:
            seat = self.seat_of(user_id)
            page = [{**f, "frame": self.frame_for(f["frame"], f["tick"], seat)}
                    for f in self.frames[start:start + limit]]
            return page, len(self.frames)

    def _seat_view(self, s: Seat) -> dict:
        return {"seat": s.seat, "occupant": s.occupant, "controller": s.public_controller(),
                "presence": self._presence(s), "submitted": s.seat in self.pending,
                "timeouts": s.timeouts}

    def view(self, user_id=None) -> dict:
        """MatchView (design 17 §7.6) for one viewer; also the snapshot event."""
        with self.lock:
            you = self.seat_of(user_id)
            return {
                "id": self.uid, "game": self.game, "version": self.version,
                "kind": self.kind, "mode": self.mode, "visibility": self.visibility,
                "invite": self.invite if you else None, "clock": self.clock,
                "status": self.status, "result": self.result,
                "seats": [self._seat_view(s) for s in self.seats.values()],
                "you": {"seat": you}, "tick": self.tick,
                "frame": self.frame_for(self.state, self.tick, you),
                "events": self.state.get("events", []), "to_act": list(self.to_act),
                "deadline_at": self.deadline_at, "rematch": self.rematch,
                "frames": len(self.frames), "created_at": self.created_at,
                "seq": self.log.seq, "server_time": _now_ms(),
            }

    # ------------------------------------------------------------- persistence
    def _players(self) -> list[dict]:
        return [{"user_id": s.occupant["user_id"], "name": s.occupant["name"], "side": s.seat}
                for s in self.seats.values() if s.occupant]

    def _models(self) -> list[dict]:
        out = []
        for s in self.seats.values():
            c = s.controller
            if c["type"] == "model":
                out.append({"type": "model", "side": s.seat, "model_id": c["model_id"],
                            "name": c.get("name"), "owner_id": c.get("owner_id")})
            elif c["type"] in ("ai", "bot"):
                out.append({"type": c["type"], "side": s.seat, "strategy": c.get("strategy")})
        return out

    def _save_seats(self) -> None:
        store.save_seats(self.row_id, [
            (s.seat, s.occupant["user_id"] if s.occupant else None, s.controller)
            for s in self.seats.values()])
        store.update_v2(self.row_id, players=self._players(), models=self._models())

    # ------------------------------------------------------------- lifecycle
    def _start(self) -> None:
        self.status = "active"
        store.update_v2(self.row_id, status="active")
        self.log.append("status", status="active", result=None)
        self._open_tick()

    def _open_tick(self) -> None:
        seats = tuple(self.seats)
        try:
            self.to_act = (self.adapter.to_act(self.state, seats)
                           if hasattr(self.adapter, "to_act") else list(seats))
        except Exception as e:
            log.exception("match %s: to_act failed", self.uid)
            self._abort("engine_error", detail=f"to_act: {type(e).__name__}: {e}")
            return
        self.pending = {}
        humans = [s for s in self.to_act if self.seats[s].human]
        timeout = self.clock.get("move_timeout_s")
        self.deadline_at = (time.time() + timeout) if (timeout and humans) else None
        if self.deadline_at:
            SCHEDULER.at(self.deadline_at, self, "deadline", self.tick)
        self._schedule_auto()

    def _waiting_on_humans(self) -> bool:
        return any(self.seats[s].human and s not in self.pending for s in self.to_act)

    def _schedule_auto(self) -> None:
        if self.status != "active" or self._waiting_on_humans():
            return
        watched = any(s.occupant for s in self.seats.values())
        SCHEDULER.at(time.time() + (AUTOPLAY_PACE_S if watched else 0.0),
                     self, "auto", self.tick)

    def _server_action(self, seat: str):
        s, owner = self.seats[seat], SEATS.index(seat)
        c = s.controller
        if c["type"] == "ai":
            out = self.adapter.ai_action({"state": self.state, "strategy": c.get("strategy"),
                                          "owner": owner})
            return out["action"] if isinstance(out, dict) and "action" in out else out
        if c["type"] == "model":
            if s._model_session is None:
                model = model_store.get_model(int(c["model_id"]))
                if model is None or model["status"] != "active":
                    raise RuntimeError(f"model {c['model_id']} unavailable")
                s._model_session = model_store.load_session(model)
            return inference.model_action(self.game, s._model_session, self.state,
                                          owner=owner, adapter=self.adapter)
        if c["type"] == "bot":
            resp = httpx.post(c["url"], json={"state": self.state, "seat": seat},
                              timeout=BOT_TIMEOUT_S)
            resp.raise_for_status()
            data = resp.json()
            return data.get("action") if isinstance(data, dict) else data
        raise RuntimeError(f"seat {seat} has no server controller")

    def _combine(self, actions: dict):
        return actions["p0"] if len(self.seats) == 1 else {s: actions[s] for s in SEATS}

    def _resolve(self) -> None:
        """Every seat in to_act has an action (or gets one now): advance one tick."""
        actions = {}
        try:
            for seat in self.seats:   # seats not to act this tick pass with the empty action
                actions[seat] = (self.pending[seat] if seat in self.pending
                                 else self._server_action(seat) if seat in self.to_act
                                 else self.empty_action)
            nxt = self.adapter.step_state(self.state, self._combine(actions))
        except Exception as e:
            log.exception("match %s: engine failure", self.uid)
            self._abort("engine_error", detail=f"{type(e).__name__}: {e}")
            return
        self.state = nxt
        self.steps += 1
        self.updated_at = time.time()
        frame = {"tick": self.tick, "frame": nxt, "actions": actions,
                 "events": nxt.get("events", [])}
        self.frames.append(frame)
        if nxt.get("done"):
            winner = nxt.get("winner")
            self.to_act, self.pending, self.deadline_at = [], {}, None
            self.log.append("tick", **frame, to_act=[], deadline_at=None)
            self._finish(f"p{winner}" if isinstance(winner, int) else winner,
                         nxt.get("cause") or "done")
            return
        if self.tick >= TICK_CAP:
            self.to_act, self.pending, self.deadline_at = [], {}, None
            self.log.append("tick", **frame, to_act=[], deadline_at=None)
            self._finish(None, "tick_cap")
            return
        self._open_tick()
        if self.status != "active":
            return   # to_act failed: the abort is already announced
        self.log.append("tick", **frame, to_act=list(self.to_act),
                        deadline_at=self.deadline_at)

    def _settle_payload(self) -> dict:
        return {"api": "v2", "match_id": self.row_id, "uid": self.uid, "game": self.game,
                "kind": self.kind, "mode": self.mode,
                "winner": self.result["winner"], "cause": self.result["cause"],
                "players": [{"user_id": p["user_id"], "seat": p["side"], "name": p["name"]}
                            for p in self._players()],
                "score": self.state.get("score"), "assisted": self.assisted,
                "seeded": self.seeded}

    def _seal(self) -> None:
        try:
            path = store.write_frames(self.uid, self.frames)
            store.update_v2(self.row_id, frames=path)
        except Exception:
            log.exception("match %s: sealing frames failed", self.uid)

    def _finish(self, winner: str | None, cause: str) -> None:
        self.status = "finished"
        self.result = {"winner": winner, "cause": cause, "tick": self.tick}
        if "score" in self.state:
            self.result["score"] = self.state["score"]
        self.finished_at = time.time()
        self.to_act, self.pending, self.deadline_at = [], {}, None
        try:
            store.update_v2(self.row_id, status="finished", result=self.result,
                            finished_at=self.finished_at)
            if self.mode == "ranked" and self.kind == "pvp":
                p0, p1 = (self.seats[s].occupant["user_id"] for s in SEATS)
                store.update_ratings(self.game, p0, p1,
                                     None if winner is None else SEATS.index(winner))
        except Exception:
            log.exception("match %s: recording the result failed", self.uid)
        events.emit("match_finished", self._settle_payload())
        self._seal()
        self.log.append("status", status="finished", result=self.result)

    def _abort(self, cause: str, *, detail: str | None = None) -> None:
        self.status = "aborted"
        self.result = {"winner": None, "cause": cause}
        if detail:
            self.result["detail"] = detail
        self.finished_at = time.time()
        self.to_act, self.pending, self.deadline_at = [], {}, None
        try:
            store.update_v2(self.row_id, status="aborted", result=self.result,
                            finished_at=self.finished_at)
        except Exception:
            log.exception("match %s: recording the abort failed", self.uid)
        self._seal()
        self.log.append("status", status="aborted", result=self.result)

    def _cancel(self, cause: str) -> None:
        self.status = "cancelled"
        self.result = {"winner": None, "cause": cause}
        self.finished_at = time.time()
        store.update_v2(self.row_id, status="cancelled", result=self.result,
                        finished_at=self.finished_at)
        self.log.append("status", status="cancelled", result=self.result)

    # ------------------------------------------------------------- commands
    def _require_live(self) -> None:
        if self.status in TERMINAL:
            raise MatchError(409, "match_over", f"对局已{self.status}")
        if self.status == "waiting":
            raise MatchError(409, "not_started", "对局尚未开始")

    def join(self, principal: dict, seat: str, invite: str | None) -> None:
        with self.lock:
            if self.status != "waiting":
                raise MatchError(409, "not_joinable", "对局已开始或已结束")
            s = self.seats.get(seat)
            if s is None:
                raise MatchError(404, "no_such_seat", f"没有座位 {seat}")
            if not s.open:
                raise MatchError(409, "seat_taken", "座位已有人")
            if self.seat_of(principal["id"]):
                raise MatchError(409, "already_seated", "你已在本局中")
            if self.visibility == "private" and (invite or "").strip().upper() != self.invite:
                raise MatchError(403, "bad_invite", "邀请码无效")
            _check_capacity(principal["id"])
            s.occupant = {"user_id": principal["id"], "name": _name(principal)}
            self._save_seats()
            self.log.append("seat", **self._seat_view(s))
            if not any(x.open for x in self.seats.values()):
                self._start()

    def submit(self, principal: dict, tick, action) -> int:
        with self.lock:
            self._require_live()
            seat = self.seat_of(principal.get("id"))
            if seat is None:
                raise MatchError(403, "not_your_seat", "你不是本局玩家")
            if not self.seats[seat].human:
                raise MatchError(409, "autopilot", "该座位正由服务端托管，先切回手动")
            if seat not in self.to_act:
                raise MatchError(403, "not_to_act", "本 tick 不轮到你出手")
            if tick != self.tick:
                raise MatchError(409, "stale_tick", "局面已更新，请基于新局面操作",
                                 current=self.tick)
            probe = action if len(self.seats) == 1 else {
                s: (action if s == seat else self.empty_action) for s in SEATS}
            try:
                self.adapter.validate_action(probe, self.state)
            except (ValueError, TypeError) as e:
                raise MatchError(422, "invalid_action", str(e))
            self.pending[seat] = action
            self.updated_at = time.time()
            seq = self.log.append("submitted", seat=seat, tick=self.tick)
            if not self._waiting_on_humans():
                self._resolve()
            return seq

    def resign(self, principal: dict) -> None:
        with self.lock:
            seat = self.seat_of(principal.get("id"))
            if seat is None:
                raise MatchError(403, "not_your_seat", "你不是本局玩家")
            if self.status in TERMINAL:
                raise MatchError(409, "match_over", f"对局已{self.status}")
            if self.status == "waiting":
                self._cancel("host_cancelled")
                return
            others = [s for s in self.seats if s != seat]
            self._finish(others[0] if others else None, "resigned")

    def set_controller(self, principal: dict, seat: str, controller: dict) -> None:
        with self.lock:
            if self.kind != "pve":
                raise MatchError(409, "not_allowed", "只有练习局可以切换托管")
            if self.seat_of(principal.get("id")) != seat:
                raise MatchError(403, "not_your_seat", "只能切换自己座位的托管")
            if self.status in TERMINAL:
                raise MatchError(409, "match_over", f"对局已{self.status}")
            s = self.seats[seat]
            s.controller = _checked_controller(self.adapter, self.game, controller,
                                               principal, own_seat=True)
            s._model_session = None
            self.assisted = self.assisted or not s.human
            self.pending.pop(seat, None)
            self._save_seats()
            self.log.append("seat", **self._seat_view(s))
            if self.status == "active":
                self._schedule_auto()

    def offer_rematch(self, principal: dict) -> dict:
        with self.lock:
            seat = self.seat_of(principal.get("id"))
            if seat is None:
                raise MatchError(403, "not_your_seat", "你不是本局玩家")
            if self.status != "finished" or self.kind != "pvp":
                raise MatchError(409, "not_allowed", "只有已结束的人类对战可以再来一局")
            r = self.rematch
            if r and r["state"] == "accepted":
                return r
            if r and r["state"] == "offered" and r["by"] != seat:
                p0, p1 = (self.seats[s].occupant for s in SEATS)
                fresh = _create(self.game, self.adapter,
                                [Seat("p0", p1, {"type": "human"}),
                                 Seat("p1", p0, {"type": "human"})],   # sides swapped
                                kind="pvp", mode=self.mode, visibility=self.visibility,
                                creator_id=principal["id"], seed=_new_seed(None))
                self.rematch = {"state": "accepted", "by": r["by"], "match_id": fresh.uid}
            elif not r or r["state"] == "expired":
                self.rematch = {"state": "offered", "by": seat,
                                "expires_at": time.time() + REMATCH_TTL}
                SCHEDULER.at(self.rematch["expires_at"], self, "rematch", self.tick)
            self.log.append("rematch", **self.rematch)
            return self.rematch

    # ------------------------------------------------------------- timers
    def on_timer(self, kind: str, tick: int) -> None:
        with self.lock:
            if kind == "rematch":
                if self.rematch and self.rematch["state"] == "offered" \
                        and time.time() >= self.rematch["expires_at"]:
                    self.rematch = {"state": "expired", "by": self.rematch["by"]}
                    self.log.append("rematch", **self.rematch)
                return
            if self.status != "active" or tick != self.tick:
                return  # stale timer: the tick already resolved
            if kind == "deadline":
                if self.deadline_at is None or time.time() < self.deadline_at:
                    return
                self._on_deadline()
            elif kind == "auto":
                if self._waiting_on_humans():
                    return
                burst = 1 if any(s.occupant for s in self.seats.values()) else BURST_TICKS
                for _ in range(burst):
                    self._resolve()
                    if self.status != "active" or self._waiting_on_humans():
                        return
                self._schedule_auto()

    def _on_deadline(self) -> None:
        for seat in self.to_act:
            s = self.seats[seat]
            if not s.human or seat in self.pending:
                continue
            s.timeouts += 1
            limit = self.clock.get("max_timeouts") or PVP_MAX_TIMEOUTS
            self.log.append("timeout", seat=seat, tick=self.tick, count=s.timeouts, max=limit)
            if (self.empty_action is None or self.clock.get("on_timeout") == "forfeit"
                    or s.timeouts >= limit):
                others = [x for x in self.seats if x != seat]
                self._finish(others[0] if others else None, "timeout")
                return
            self.pending[seat] = self.empty_action
        self._resolve()

    # ------------------------------------------------------------- presence
    def connect(self, user_id) -> None:
        with self.lock:
            self.viewers += 1
            seat = self.seat_of(user_id)
            if seat is None:
                return
            self.presence[user_id] = self.presence.get(user_id, 0) + 1
            if self.presence[user_id] == 1:
                self.log.append("seat", **self._seat_view(self.seats[seat]))

    def disconnect(self, user_id) -> None:
        with self.lock:
            self.viewers -= 1
            seat = self.seat_of(user_id)
            if seat is None or not self.presence.get(user_id):
                return
            self.presence[user_id] -= 1
            if self.presence[user_id] == 0:
                del self.presence[user_id]
                self.log.append("seat", **self._seat_view(self.seats[seat]))


# ------------------------------------------------------------------ scheduler

class _Scheduler:
    """One thread keeps every match's timers; due timers run on a small pool so a
    long burst never delays another match's deadline. It also sweeps idle,
    unjoined and expired matches."""

    SWEEP_S = 30.0

    def __init__(self):
        self._heap: list = []
        self._count = itertools.count()
        self._cv = threading.Condition()
        self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="match")
        self._thread: threading.Thread | None = None
        self._next_sweep = 0.0

    def at(self, when: float, match: Match, kind: str, tick: int) -> None:
        with self._cv:
            heapq.heappush(self._heap, (when, next(self._count), match.uid, kind, tick))
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, name="match-scheduler",
                                                daemon=True)
                self._thread.start()
            self._cv.notify()

    def _run(self) -> None:
        while True:
            with self._cv:
                now = time.time()
                due = []
                while self._heap and self._heap[0][0] <= now:
                    due.append(heapq.heappop(self._heap))
                if not due:
                    wait = min(self.SWEEP_S, (self._heap[0][0] - now) if self._heap else self.SWEEP_S)
                    self._cv.wait(timeout=max(wait, 0.0))
            for _, _, uid, kind, tick in due:
                match = LIVE.get(uid)
                if match is not None:
                    self._pool.submit(_fire, match, kind, tick)
            if time.time() >= self._next_sweep:
                self._next_sweep = time.time() + self.SWEEP_S
                self._pool.submit(sweep)


def _fire(match: Match, kind: str, tick: int) -> None:
    try:
        match.on_timer(kind, tick)
    except Exception:
        log.exception("match %s: timer %s failed", match.uid, kind)


SCHEDULER = _Scheduler()
LIVE: dict[str, Match] = {}
_LIVE_LOCK = threading.Lock()


def sweep(now: float | None = None) -> None:
    now = now or time.time()
    with _LIVE_LOCK:
        live = list(LIVE.values())
    for m in live:
        with m.lock:
            if m.status == "waiting" and now - m.created_at > WAITING_TTL:
                m._cancel("waiting_timeout")
            elif (m.status == "active" and m.deadline_at is None
                  and now - m.updated_at > IDLE_TTL):
                m._abort("idle")
            elif (m.status in TERMINAL and m.viewers <= 0
                  and now - (m.finished_at or now) > RETAIN_S):
                with _LIVE_LOCK:
                    LIVE.pop(m.uid, None)


# ------------------------------------------------------------------ creation

def _invite_code() -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=6))


def _new_seed(seed) -> int:
    return int(seed) if seed is not None else int(time.time() * 1000) % (1 << 30)


def _check_capacity(user_id) -> None:
    with _LIVE_LOCK:
        mine = sum(1 for m in LIVE.values() if m.status in ("waiting", "active")
                   and m.seat_of(user_id))
    if mine >= MAX_LIVE_PER_USER:
        raise MatchError(429, "too_many_matches", f"同时进行的对局已达上限（{MAX_LIVE_PER_USER}）")


def _checked_controller(adapter, game: str, c, principal: dict, *, own_seat: bool) -> dict:
    if not isinstance(c, dict) or c.get("type") not in ("human", "ai", "model", "bot"):
        raise MatchError(400, "bad_controller", "controller.type 需为 human/ai/model/bot")
    kind = c["type"]
    if kind == "human":
        return {"type": "human"}
    if kind == "ai":
        strategies = list(getattr(adapter, "opponents", None) or []) + \
            list((getattr(adapter, "meta", None) or {}).get("ai_strategies") or [])
        strategy = c.get("strategy") or getattr(adapter, "default_opponent", None) \
            or (strategies[0] if strategies else None)
        if strategy not in strategies:
            raise MatchError(400, "bad_controller", f"未知策略 {strategy!r}（可选 {strategies}）")
        return {"type": "ai", "strategy": strategy}
    if kind == "model":
        if not inference.supports_models(game):
            raise MatchError(400, "bad_controller", f"游戏 {game!r} 未声明模型契约")
        try:
            model = model_store.get_model(int(c.get("model_id")))
        except (TypeError, ValueError):
            model = None
        if model is None or model["status"] != "active" or model["game"] != game:
            raise MatchError(400, "bad_controller", "模型不存在或不属于本游戏")
        if own_seat and model["owner_id"] != principal.get("id"):
            raise MatchError(403, "bad_controller", "只能用自己的模型代打")
        return {"type": "model", "model_id": model["id"], "name": model["name"],
                "owner_id": model["owner_id"]}
    url = c.get("url")
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        raise MatchError(400, "bad_controller", "bot.url 需为 http(s) 地址")
    return {"type": "bot", "url": url}


def seat_count(adapter) -> int:
    declared = (getattr(adapter, "meta", None) or {}).get("seats")
    if declared:
        return int(declared)
    return 2 if (getattr(adapter, "pvp_enabled", False)
                 or getattr(adapter, "opponents", None)) else 1


def clock_for(adapter, kind: str) -> dict:
    """The package's declared clock, else the platform default. Move deadlines
    bind only when one human's delay holds up another human (kind pvp)."""
    declared = (getattr(adapter, "meta", None) or {}).get("clock")
    clock = dict(declared) if declared else {
        "kind": "turn", "move_timeout_s": PVP_MOVE_TIMEOUT_S, "on_timeout": "empty",
        "max_timeouts": PVP_MAX_TIMEOUTS}
    if kind != "pvp":
        clock["move_timeout_s"] = None
    return clock


def _create(game, adapter, seats: list[Seat], *, kind, mode, visibility, creator_id,
            seed, seeded: bool = False) -> Match:
    for s in seats:
        if s.occupant:
            _check_capacity(s.occupant["user_id"])
    clock = clock_for(adapter, kind)
    try:
        m = Match(game=game, adapter=adapter, seats=seats, kind=kind, mode=mode,
                  visibility=visibility, creator_id=creator_id, seed=seed, clock=clock,
                  seeded=seeded)
    except (ValueError, TypeError) as e:
        raise MatchError(400, "bad_settings", f"开局失败：{e}")
    m.row_id = store.insert_v2(m.uid, game, kind, m.version, mode, visibility, clock,
                               m._players(), m._models(), "waiting", m.created_at)
    m._save_seats()
    with _LIVE_LOCK:
        LIVE[m.uid] = m
    with m.lock:
        if not any(s.open for s in m.seats.values()):
            m._start()
    return m


def create_match(principal: dict, spec: dict) -> Match:
    """POST /api/v2/matches. ``spec = {game, seats?, mode?, visibility?, settings?}``;
    each seat is ``{seat, occupant: "me" | None, controller}``."""
    if not principal.get("id"):
        raise MatchError(401, "login_required", "请先登录")
    game = spec.get("game")
    adapter = registry.GAMES.get(game)
    if adapter is None:
        raise MatchError(404, "unknown_game", f"游戏 {game!r} 不存在")
    n = seat_count(adapter)
    raw = spec.get("seats")
    if raw is None:   # default: me against the game's default opponent, if any
        raw = [{"seat": "p0", "occupant": "me", "controller": {"type": "human"}}]
        if n == 2:
            raw.append({"seat": "p1", "occupant": None,
                        "controller": {"type": "ai"} if getattr(adapter, "opponents", None)
                        else {"type": "human"}})
    if not isinstance(raw, list) or sorted(s.get("seat") for s in raw if isinstance(s, dict)) \
            != list(SEATS[:n]):
        raise MatchError(400, "bad_seats", f"本游戏需要座位 {list(SEATS[:n])}")
    seats, mine, open_humans, my_models = [], 0, 0, 0
    for item in sorted(raw, key=lambda s: s["seat"]):
        occupant = item.get("occupant")
        if occupant not in ("me", None):
            raise MatchError(400, "bad_seats", "occupant 只能是 \"me\" 或 null")
        own = occupant == "me"
        ctl = _checked_controller(adapter, game, item.get("controller") or {"type": "human"},
                                  principal, own_seat=own)
        if own:
            mine += 1
            occ = {"user_id": principal["id"], "name": _name(principal)}
        else:
            occ = None
            open_humans += ctl["type"] == "human"
            my_models += ctl["type"] == "model" and ctl.get("owner_id") == principal["id"]
        seats.append(Seat(item["seat"], occ, ctl))
    if mine > 1:
        raise MatchError(400, "bad_seats", "不能同时占两个座位")
    if mine == 0 and (open_humans or not my_models):
        raise MatchError(400, "bad_seats", "无人座位的对局需要至少一个你自己的模型")
    kind = "pvp" if mine + open_humans >= 2 else ("pve" if mine else "model_vs_model")
    if kind == "pvp":
        if not getattr(adapter, "pvp_enabled", False):
            raise MatchError(400, "no_pvp", f"游戏 {game!r} 不支持人类对战")
        if not all(s.human for s in seats):
            raise MatchError(400, "bad_seats", "人类对战的座位都必须由人手动操作")
        mode = spec.get("mode") or "casual"   # D10: rooms default to casual
        if mode not in ("ranked", "casual"):
            raise MatchError(400, "bad_mode", "人类对战的 mode 需为 ranked 或 casual")
    else:
        mode = spec.get("mode") or "practice"
        if mode != "practice":
            raise MatchError(400, "bad_mode", "只有人类对战可以计分")
    visibility = spec.get("visibility") or ("unlisted" if kind == "pve" else "public")
    if visibility not in ("public", "unlisted", "private"):
        raise MatchError(400, "bad_visibility", "visibility 需为 public/unlisted/private")
    settings = spec.get("settings") or {}
    if not isinstance(settings, dict) or set(settings) - {"seed"}:
        raise MatchError(400, "bad_settings", "settings 目前只支持 seed")
    return _create(game, adapter, seats, kind=kind, mode=mode, visibility=visibility,
                   creator_id=principal["id"], seed=_new_seed(settings.get("seed")),
                   seeded=settings.get("seed") is not None)


def create_paired(game: str, mode: str, first: dict, second: dict) -> Match:
    """Matchmaking: both seats filled, starts immediately (watchable: public)."""
    adapter = registry.GAMES[game]
    return _create(game, adapter,
                   [Seat("p0", {"user_id": first["id"], "name": _name(first)}, {"type": "human"}),
                    Seat("p1", {"user_id": second["id"], "name": _name(second)}, {"type": "human"})],
                   kind="pvp", mode=mode, visibility="public", creator_id=first["id"],
                   seed=_new_seed(None))


# ------------------------------------------------------------------ queries

def get_live(uid: str) -> Match | None:
    return LIVE.get(uid)


def can_read(visibility: str, seated: bool) -> bool:
    """Design 17 §4.5: private matches are readable only by their players."""
    return seated or visibility in ("public", "unlisted")


def lobby(game: str, mode: str | None = None) -> list[dict]:
    with _LIVE_LOCK:
        live = list(LIVE.values())
    rooms = []
    for m in live:
        if (m.game == game and m.status == "waiting" and m.visibility == "public"
                and (mode is None or m.mode == mode)):
            host = next((s.occupant for s in m.seats.values() if s.occupant), None)
            rooms.append({"id": m.uid, "game": m.game, "mode": m.mode,
                          "visibility": m.visibility, "host": host and host["name"],
                          "host_id": host and host["user_id"],
                          "open_seats": [s.seat for s in m.seats.values() if s.open],
                          "created_at": m.created_at})
    return sorted(rooms, key=lambda r: r["created_at"])


def my_live(user_id) -> list[dict]:
    with _LIVE_LOCK:
        live = list(LIVE.values())
    mine = [m for m in live if m.status in ("waiting", "active") and m.seat_of(user_id)]
    mine.sort(key=lambda m: m.updated_at, reverse=True)
    return [m.view(user_id) for m in mine]


def has_live_pair(game: str, uid0: int, uid1: int) -> bool:
    with _LIVE_LOCK:
        live = list(LIVE.values())
    return any(m.game == game and m.kind == "pvp" and m.status in ("waiting", "active")
               and {s.occupant["user_id"] for s in m.seats.values() if s.occupant} == {uid0, uid1}
               for m in live)


def record_view(rec: dict, user_id=None) -> dict:
    """MatchView of a match that is no longer live (finished long ago, or the
    server restarted), rebuilt from its record and sealed frames."""
    seats = [{"seat": s["seat"], "controller": {k: v for k, v in s["controller"].items()
                                                if k != "url"},
              "occupant": next(({"user_id": p["user_id"], "name": p["name"]}
                                for p in rec["players"] if p.get("side") == s["seat"]), None),
              "presence": "offline", "submitted": False, "timeouts": 0}
             for s in rec["seats"]]
    you = next((s["seat"] for s in seats if s["occupant"] and user_id is not None
                and s["occupant"]["user_id"] == user_id), None)
    frames = store.read_frames(rec["frames"]) if rec.get("frames") else []
    last = frames[-1] if frames else {"tick": 0, "frame": None, "events": []}
    return {"id": rec["uid"], "game": rec["game"], "version": rec["version"],
            "kind": rec["kind"], "mode": rec["mode"], "visibility": rec["visibility"],
            "invite": None, "clock": rec["clock"], "status": rec["status"],
            "result": rec["result"], "seats": seats, "you": {"seat": you},
            "tick": last["tick"], "frame": last["frame"], "events": last.get("events", []),
            "to_act": [], "deadline_at": None, "rematch": None, "frames": len(frames),
            "created_at": rec["created_at"], "seq": 0, "server_time": _now_ms()}
