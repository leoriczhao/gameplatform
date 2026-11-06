"""One-off offline migration of v1 match records to the v2 stage (design 17 M4).

v1 records live in the same ``matches`` table but have no ``uid`` and no sealed
frames. This script, run once against a stopped/before-restart database:

* assigns every legacy row a random 12-hex ``uid`` so old ``/watch/match/{id}``
  links can be redirected to ``/m/{uid}``;
* rebuilds sealed frames from the v1 ``replay`` payload (``game_version`` /
  ``seed`` / ``options`` / ``moves``) with the matching versioned adapter;
* keeps the result when a replay cannot be rebuilt and marks it as unavailable
  (frames stay NULL), instead of dropping the match;
* fills ``mode`` / ``visibility`` / ``version`` / ``clock`` and the v2
  ``match_seats`` rows;
* marks stale ``queued`` / ``running`` rows from a previous process as aborted
  (in-memory sessions are lost on restart, D12).

It is idempotent: rows that already have a uid are skipped. Run it ONLY as an
offline migration, after a backup, with the new version's code available:

    SCORES_DB=/data/scores.db .venv/bin/python backend/migrate_legacy_matches.py --dry-run
    SCORES_DB=/data/scores.db .venv/bin/python backend/migrate_legacy_matches.py

This is a data migration, not an API compatibility layer: v1 play endpoints are
gone and old SDKs receive 404 after the M4 release.
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import secrets
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import registry  # noqa: E402

MAX_FRAMES = 20_000
VISIBILITY = "unlisted"   # legacy rooms lost their original visibility; link-only
DEFAULT_CLOCK = {"kind": "turn", "move_timeout_s": None, "on_timeout": "empty",
                 "max_timeouts": 0}
V2_COLUMNS = {"uid": "TEXT", "mode": "TEXT", "visibility": "TEXT",
              "version": "TEXT", "clock": "TEXT", "frames": "TEXT"}
MATCHES_DDL = """CREATE TABLE IF NOT EXISTS matches (
       id INTEGER PRIMARY KEY AUTOINCREMENT,
       game TEXT NOT NULL,
       kind TEXT NOT NULL,
       players TEXT NOT NULL,
       models TEXT NOT NULL DEFAULT '[]',
       status TEXT NOT NULL,
       result TEXT,
       replay TEXT,
       created_at REAL NOT NULL,
       finished_at REAL
   )"""
SEATS_DDL = """CREATE TABLE IF NOT EXISTS match_seats (
       match_id INTEGER NOT NULL, seat TEXT NOT NULL,
       user_id INTEGER, controller TEXT NOT NULL,
       PRIMARY KEY (match_id, seat))"""


def _loads(raw, default):
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default


def connect(db_path: str) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    """v2 columns/tables are additive; a pre-v2 database may lack them."""
    conn.execute(MATCHES_DDL)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(matches)")}
    for col, kind in V2_COLUMNS.items():
        if col not in cols:
            conn.execute(f"ALTER TABLE matches ADD COLUMN {col} {kind}")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_matches_uid ON matches(uid)")
    conn.execute(SEATS_DDL)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_seats_user ON match_seats(user_id)")
    conn.commit()


def _new_uid(conn: sqlite3.Connection, has_uid: bool = True) -> str:
    while True:
        uid = secrets.token_hex(6)
        if not has_uid:
            return uid
        hit = conn.execute("SELECT 1 FROM matches WHERE uid=?", (uid,)).fetchone()
        if hit is None:
            return uid


def _adapter(game: str, version: str | None):
    """Resolve the exact versioned adapter; never silently substitute a version."""
    return registry.resolve(game, version)


def _clock(adapter, kind: str) -> dict:
    declared = (getattr(adapter, "meta", None) or {}).get("clock")
    clock = dict(declared) if declared else dict(DEFAULT_CLOCK)
    if kind != "pvp":
        clock["move_timeout_s"] = None
    return clock


def _mode(kind: str, result: dict) -> str:
    if kind == "pvp":
        return result.get("mode") if result.get("mode") in ("ranked", "casual") else "casual"
    return "practice"


def _normalize_result(result, status: str) -> dict | None:
    if status in ("queued", "running"):
        return {"winner": None, "cause": "server_restart"}
    if not isinstance(result, dict):
        return result
    out = dict(result)
    winner = out.get("winner")
    if isinstance(winner, int) and winner in (0, 1):
        out["winner"] = f"p{winner}"
    elif not isinstance(winner, str):
        out["winner"] = None
    return out


def _seat_rows(row, adapter) -> list[tuple[str, int | None, dict]]:
    seats: dict[str, tuple[int | None, dict]] = {}
    for player in _loads(row["players"], []):
        side = player.get("side") if isinstance(player, dict) else None
        if side in ("p0", "p1"):
            seats[side] = (player.get("user_id"), {"type": "human"})
    for model in _loads(row["models"], []):
        if not isinstance(model, dict):
            continue
        side = model.get("side")
        if side not in ("p0", "p1") or side in seats:
            continue
        kind = model.get("type")
        if kind == "model":
            controller = {"type": "model", "model_id": model.get("model_id")}
        elif kind in ("ai", "bot"):
            controller = {"type": kind, "strategy": model.get("strategy")}
        else:
            continue
        for key in ("name", "owner_id"):
            if key in model:
                controller[key] = model[key]
        seats[side] = (None, controller)
    if not seats:
        seats["p0"] = (None, {"type": "human"})
    # A two-seat PvE replay embedded the server opponent commands but recorded
    # only p0: restore the AI seat so the stage has two seats.
    if len(seats) == 1 and _replay_has_opponent(row):
        seats["p1"] = (None, {"type": "ai"})
    return [(seat, occupant, controller)
            for seat, (occupant, controller) in sorted(seats.items())]


def _replay_has_opponent(row) -> bool:
    replay = _loads(row["replay"], None)
    moves = replay.get("moves") if isinstance(replay, dict) else None
    return any(isinstance(move, dict) and move.get("opponent") is not None
               for move in (moves or []))


def _combine(move: dict):
    action = move.get("action")
    if isinstance(action, dict) and "p0" in action:
        return {"p0": action.get("p0", []), "p1": action.get("p1", [])}
    if move.get("opponent") is not None:
        return {"p0": action, "p1": move["opponent"]}
    return action


def build_frames(row, adapter) -> list[dict] | None:
    """Rebuild the v2 sealed frames from one v1 replay payload, else None."""
    raw = _loads(row["replay"], None)
    if not isinstance(raw, dict):
        return None  # very old plain move lists carry no seed: not replayable
    seed = raw.get("seed")
    moves = raw.get("moves")
    if seed is None or not isinstance(moves, list) or len(moves) > MAX_FRAMES:
        return None
    options = raw.get("options")
    if options is None and len(_seat_rows(row, adapter)) == 2:
        options = getattr(adapter, "pvp_options", None)
    try:
        state = adapter.new_state(seed, options) if options is not None else adapter.new_state(seed)
    except Exception:
        return None
    frames = [{"tick": int(state.get("tick", 0)), "frame": state, "actions": None,
               "events": state.get("events", [])}]
    try:
        for move in moves:
            if not isinstance(move, dict):
                return None
            combined = _combine(move)
            state = adapter.step_state(state, combined)
            actions = combined if isinstance(combined, dict) else {"p0": combined}
            frames.append({"tick": int(move.get("tick", state.get("tick", 0))),
                           "frame": state, "actions": actions,
                           "events": state.get("events", [])})
    except Exception:
        return None
    return frames


def _write_frames(db_path: str, uid: str, frames: list[dict]) -> str:
    path = Path(db_path).parent / "replays" / f"{uid}.jsonl.gz"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as fh:
        for frame in frames:
            fh.write(json.dumps(frame, ensure_ascii=False, separators=(",", ":")) + "\n")
    tmp.replace(path)
    return str(path)


def migrate(db_path: str, *, dry_run: bool = False, limit: int | None = None,
            log=print) -> dict:
    """Migrate legacy rows in-place; returns counters. Idempotent."""
    conn = connect(db_path)
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(matches)")}
        if not dry_run:
            ensure_schema(conn)
        select = ("id, game, kind, players, models, status, result, replay, "
                  "created_at, finished_at" + (", uid" if "uid" in cols else ", NULL AS uid"))
        rows = conn.execute(f"SELECT {select} FROM matches ORDER BY id").fetchall()
        counts = {"scanned": 0, "migrated": 0, "unavailable": 0, "aborted": 0,
                  "skipped": 0, "errors": 0}
        for row in rows:
            if limit is not None and counts["migrated"] + counts["unavailable"] >= limit:
                break
            counts["scanned"] += 1
            if row["uid"]:
                counts["skipped"] += 1
                continue
            kind = row["kind"]
            status = row["status"]
            result = _normalize_result(_loads(row["result"], None), status)
            adapter = None
            version = None
            replay = _loads(row["replay"], None)
            if isinstance(replay, dict):
                version = replay.get("game_version")
            try:
                adapter = _adapter(row["game"], version)
                version = version or (getattr(adapter, "meta", None) or {}).get("version")
            except Exception as e:
                log(f"  row {row['id']} ({row['game']} {kind}): no adapter for "
                    f"version {version!r}: {type(e).__name__}: {e}")
            clock = _clock(adapter, kind) if adapter is not None else dict(DEFAULT_CLOCK)
            mode = _mode(kind, result or {})
            uid = _new_uid(conn, has_uid="uid" in cols)
            frames = None
            if status == "finished" and adapter is not None:
                frames = build_frames(row, adapter)
            new_status = status
            if status in ("queued", "running"):
                new_status = "aborted"
                counts["aborted"] += 1
            elif status == "failed":
                new_status = "aborted"
            frame_path = None
            if frames is not None:
                counts["migrated"] += 1
                if not dry_run:
                    try:
                        frame_path = _write_frames(db_path, uid, frames)
                    except Exception as e:
                        log(f"  row {row['id']}: write frames failed: {e}")
                        counts["errors"] += 1
                        frames = None
            elif status == "finished":
                counts["unavailable"] += 1
            if dry_run:
                continue
            seats = _seat_rows(row, adapter) if adapter is not None else []
            try:
                conn.execute(
                    "UPDATE matches SET uid=?, mode=?, visibility=?, version=?, "
                    "clock=?, frames=?, status=?, result=? WHERE id=?",
                    (uid, mode, VISIBILITY, version, json.dumps(clock, ensure_ascii=False),
                     frame_path, new_status,
                     json.dumps(result, ensure_ascii=False) if result is not None else None,
                     row["id"]))
                conn.execute("DELETE FROM match_seats WHERE match_id=?", (row["id"],))
                conn.executemany(
                    "INSERT INTO match_seats (match_id, seat, user_id, controller) "
                    "VALUES (?,?,?,?)",
                    [(row["id"], seat, occupant, json.dumps(controller, ensure_ascii=False))
                     for seat, occupant, controller in seats])
                conn.commit()
            except Exception as e:
                conn.rollback()
                counts["errors"] += 1
                counts["migrated"] -= 1 if frames is not None else 0
                counts["unavailable"] += 1
                log(f"  row {row['id']}: db update failed: {e}")
        if not dry_run:
            conn.commit()
        return counts
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default=os.environ.get("SCORES_DB", "/data/scores.db"))
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would change without writing")
    parser.add_argument("--limit", type=int, default=None,
                        help="at most N rows to migrate (smoke test)")
    args = parser.parse_args(argv)
    if not registry.GAMES:   # register official packaged games like the server does
        import main  # noqa: F401
    started = time.time()
    counts = migrate(args.db, dry_run=args.dry_run, limit=args.limit)
    print(f"{'[dry-run] ' if args.dry_run else ''}legacy match migration "
          f"{args.db} in {time.time() - started:.1f}s: {counts}")
    return 0 if counts["errors"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
