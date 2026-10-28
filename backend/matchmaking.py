"""Quick matchmaking v2 (design 17 §5.3; 06 §5 band semantics kept).

- ranked: initial band ±100, +100 every 5s up to ±400, any opponent after 60s.
- casual: any rating difference from the start (06 §5.2).
- a matched pair becomes a normal v2 Match (match_engine.create_paired): both
  human seats filled, starts immediately, public/watchable.
- Both players poll GET /api/v2/{game}/matchmaking/status for the match id.
- Everything is in-memory (D12): restart loses queues.
"""
from __future__ import annotations

import threading
import time

import match_engine
import matches as match_store
from registry import GAMES

SCAN_INTERVAL = 2.0            # background scan period (s)
QUEUE_TIMEOUT = 10 * 60        # auto-remove after 10 min
BAND_START = 100
BAND_STEP = 100
BAND_STEP_SECONDS = 5
BAND_MAX = 400
BAND_ANY_SECONDS = 60          # ranked: any opponent after 60s
CASUAL_ANY = True              # casual matches any rating difference


def _now() -> float:
    """Indirection for tests (monkeypatch matchmaking._now)."""
    return time.time()


class QueueEntry:
    def __init__(self, game: str, mode: str, principal: dict):
        self.game = game
        self.mode = mode
        self.principal = principal
        self.enqueued_at = _now()
        self.matched_at = 0.0
        self.match_uid: str | None = None


_QUEUES: dict[tuple[str, str], list[QueueEntry]] = {}
_LOCK = threading.Lock()
_MATCH_LOCK = threading.Lock()


def get_rating(game: str, user_id: int) -> float:
    return match_store.get_rating(game, user_id)


def _band_for(entry: QueueEntry) -> float:
    if entry.mode == "casual" and CASUAL_ANY:
        return float("inf")
    waited = _now() - entry.enqueued_at
    if waited > BAND_ANY_SECONDS:
        return float("inf")
    band = BAND_START + (waited // BAND_STEP_SECONDS) * BAND_STEP
    return min(band, BAND_MAX)


def join_queue(game: str, principal: dict, mode: str,
               api: str = "v2") -> QueueEntry:
    """Enter the queue for (game, mode); re-enqueueing updates the mode.

    The api argument is kept for the v2 endpoint call site; matchmaking only
    pairs v2 matches now. Raises ValueError / PermissionError."""
    if not principal.get("id"):
        raise PermissionError("快速匹配需要登录")
    adapter = GAMES.get(game)
    if adapter is None or not getattr(adapter, "pvp_enabled", False):
        raise ValueError(f"游戏 {game!r} 不支持快速匹配")
    if mode not in ("ranked", "casual"):
        raise ValueError("mode 必须是 ranked 或 casual")
    with _LOCK:
        # one queue per user per game: replace any existing entry (D9/07 M2)
        for key in list(_QUEUES):
            _QUEUES[key] = [e for e in _QUEUES[key]
                            if not (e.game == game
                                    and e.principal["id"] == principal["id"])]
        entry = QueueEntry(game, mode, principal)
        _QUEUES.setdefault((game, mode), []).append(entry)
    try_match()
    return entry


def leave_queue(game: str, principal: dict) -> bool:
    """Cancel queueing; True if an entry was actually removed."""
    with _LOCK:
        removed = False
        for key in list(_QUEUES):
            keep, drop = [], []
            for e in _QUEUES[key]:
                if e.game == game and e.principal["id"] == principal["id"]:
                    drop.append(e)
                    removed = True
                else:
                    keep.append(e)
            if drop:
                _QUEUES[key] = keep
        for key in [k for k, q in _QUEUES.items() if not q]:
            del _QUEUES[key]
    return removed


def queue_status(game: str, principal: dict) -> dict:
    """Current queue state for one user: queued (position/wait) or matched
    (match id; the entry stays readable on repeated polls)."""
    now = _now()
    with _LOCK:
        entry = None
        for (g, mode), q in _QUEUES.items():
            for e in q:
                if e.game == game and e.principal["id"] == principal["id"]:
                    entry = e
                    break
            if entry:
                break
        if entry is None:
            return {"queued": False, "matched": False, "mode": None,
                    "position": None, "wait_seconds": 0, "match_id": None}
        if entry.match_uid:
            return {"queued": False, "matched": True, "mode": entry.mode,
                    "position": None, "wait_seconds": int(now - entry.enqueued_at),
                    "match_id": entry.match_uid}
        q = _QUEUES[(game, entry.mode)]
        waiting = [e for e in q if e.match_uid is None]
        position = waiting.index(entry) + 1
        return {"queued": True, "matched": False, "mode": entry.mode,
                "position": position,
                "wait_seconds": int(now - entry.enqueued_at),
                "match_id": None}


def _expire(now: float) -> None:
    with _LOCK:
        for key in list(_QUEUES):
            _QUEUES[key] = [e for e in _QUEUES[key]
                            if ((e.match_uid is None
                                 and now - e.enqueued_at < QUEUE_TIMEOUT)
                                or (e.match_uid is not None
                                    and now - e.matched_at < QUEUE_TIMEOUT))]
            if not _QUEUES[key]:
                del _QUEUES[key]


def _find_pairs() -> list[tuple[str, str, QueueEntry, QueueEntry]]:
    """Collect compatible pairs from every queue (oldest first, band-checked).
    Anti-farming: same account never pairs; an unfinished match between the
    same two users blocks re-matching (06 §5.2)."""
    pairs: list[tuple[str, str, QueueEntry, QueueEntry]] = []
    with _LOCK:
        for (game, mode), q in _QUEUES.items():
            if len(q) < 2:
                continue
            q.sort(key=lambda e: e.enqueued_at)
            i = 0
            while i < len(q):
                e0 = q[i]
                if e0.match_uid or e0.matched_at:
                    i += 1
                    continue
                band0 = _band_for(e0)
                for j in range(i + 1, len(q)):
                    e1 = q[j]
                    if e1.match_uid or e1.matched_at:
                        continue
                    if e0.principal["id"] == e1.principal["id"]:
                        continue
                    if match_engine.has_live_pair(game, e0.principal["id"],
                                                  e1.principal["id"]):
                        continue
                    diff = abs(get_rating(game, e0.principal["id"])
                               - get_rating(game, e1.principal["id"]))
                    if diff > min(band0, _band_for(e1)):
                        continue
                    e0.matched_at = e1.matched_at = _now()
                    pairs.append((game, mode, e0, e1))
                    break
                i += 1
    return pairs


def _pair_matches(pairs) -> None:
    """Create the paired v2 matches for matched queue entries."""
    for game, mode, e0, e1 in pairs:
        try:
            match = match_engine.create_paired(game, mode, e0.principal,
                                               e1.principal)
        except match_engine.MatchError:
            # capacity / engine error: reset the pair and retry next scan
            with _LOCK:
                e0.matched_at = e1.matched_at = 0.0
            continue
        with _LOCK:
            e0.match_uid = e1.match_uid = match.uid


def try_match() -> None:
    """One scan pass: expire stale entries, pair compatible seekers, create
    matches. Called from the background loop and after every enqueue."""
    with _MATCH_LOCK:
        _expire(_now())
        pairs = _find_pairs()
        if pairs:
            _pair_matches(pairs)


def tick() -> None:
    try_match()
