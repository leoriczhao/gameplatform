"""Match records, ELO ratings, and v2 match persistence.

Design: docs/design/17（v2 对局）+ 03（历史 v1 记录）.

- v2 matches (PvE/PvP/model seats) are created in SQLite on creation
  (insert_v2), get their seats/frames persisted, and finish with update_v2.
- The matches table also keeps archived v1 rows (kind pvp/pve/model_vs_model
  with a replay JSON column). Those columns and rows stay readable for the
  history APIs and the one-off M4 migration script; no v1 writer remains.
- ELO bookkeeping (K=32, start 1200) is shared by v2 ranked matches.
"""
from __future__ import annotations

import gzip
import json
import sqlite3
import time
from pathlib import Path

SCORES_DB = Path(__import__("os").environ.get("SCORES_DB", "/data/scores.db"))

_K = 32
_START_RATING = 1200


def _db() -> sqlite3.Connection:
    SCORES_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(SCORES_DB, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS matches (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               game TEXT NOT NULL,
               kind TEXT NOT NULL,           -- pvp | pve | model_vs_model
               players TEXT NOT NULL,        -- JSON [{user_id, name, side}]
               models TEXT NOT NULL DEFAULT '[]',  -- JSON [model_id, ...]
               status TEXT NOT NULL,         -- waiting | active | finished | ...
               result TEXT,                  -- JSON {winner, cause, ...}
               replay TEXT,                  -- archived v1 rows only (M4 keeps the column)
               created_at REAL NOT NULL,
               finished_at REAL
           )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS rating_history (
               id INTEGER PRIMARY KEY AUTOINCREMENT, game TEXT NOT NULL,
               user_id INTEGER NOT NULL, rating REAL NOT NULL,
               created_at REAL NOT NULL)""")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_rh_game_user ON rating_history(game, user_id, id)")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS ratings (
               game TEXT NOT NULL,
               user_id INTEGER NOT NULL,
               rating REAL NOT NULL,
               games INTEGER NOT NULL DEFAULT 0,
               wins INTEGER NOT NULL DEFAULT 0,
               PRIMARY KEY (game, user_id)
           )"""
    )
    _ensure_v2_schema(conn)
    return conn


# v2 对局（设计 17）：记录仍在 matches 表，创建即落库；uid 为对外 id（不可猜，
# unlisted 凭链接可读的前提），座位进 match_seats。
_V2_COLUMNS = {"uid": "TEXT", "mode": "TEXT", "visibility": "TEXT",
               "version": "TEXT", "clock": "TEXT", "frames": "TEXT"}
_V2_READY: set[str] = set()


def _ensure_v2_schema(conn) -> None:
    if str(SCORES_DB) in _V2_READY:
        return
    cols = {r[1] for r in conn.execute("PRAGMA table_info(matches)")}
    for col, kind in _V2_COLUMNS.items():
        if col not in cols:
            conn.execute(f"ALTER TABLE matches ADD COLUMN {col} {kind}")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_matches_uid ON matches(uid)")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS match_seats (
               match_id INTEGER NOT NULL, seat TEXT NOT NULL,
               user_id INTEGER, controller TEXT NOT NULL,
               PRIMARY KEY (match_id, seat))""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_seats_user ON match_seats(user_id)")
    conn.commit()
    _V2_READY.add(str(SCORES_DB))


def _row(row, columns=None) -> dict:
    # v2 的 uid / mode / visibility / version 是 ALTER TABLE 追加的列，历史库的
    # 物理顺序可能不同，所以按 cursor.description 里的列名取值；前端
    # /matches → /m/:id 需要 uid（设计 17 M3）。
    out = {"id": row[0], "game": row[1], "kind": row[2],
           "players": json.loads(row[3] or "[]"),
           "models": json.loads(row[4] or "[]"),
           "status": row[5],
           "result": json.loads(row[6]) if row[6] else None,
           "replay": json.loads(row[7]) if row[7] else None,
           "created_at": row[8], "finished_at": row[9]}
    if columns:
        by_name = dict(zip(columns, row))
        out["uid"] = by_name.get("uid")
        out["mode"] = by_name.get("mode")
        out["visibility"] = by_name.get("visibility")
        out["version"] = by_name.get("version")
    return out


# ----------------------------------------------------------------- ratings

def _get_ratings(conn, game: str, user_ids: list[int]) -> dict[int, float]:
    out = {}
    for uid in set(user_ids):
        row = conn.execute(
            "SELECT rating FROM ratings WHERE game=? AND user_id=?",
            (game, uid)).fetchone()
        out[uid] = row[0] if row else float(_START_RATING)
    return out


def get_rating(game: str, user_id: int) -> float:
    """Current ELO for one user/game (1200 default); used by matchmaking."""
    conn = _db()
    try:
        row = conn.execute(
            "SELECT rating FROM ratings WHERE game=? AND user_id=?",
            (game, user_id)).fetchone()
    finally:
        conn.close()
    return row[0] if row else float(_START_RATING)


def update_ratings(game: str, p0_id: int, p1_id: int, winner: int | None) -> None:
    """ELO update after a finished human PvP match (winner None = draw)."""
    conn = _db()
    try:
        ratings = _get_ratings(conn, game, [p0_id, p1_id])
        ra, rb = ratings[p0_id], ratings[p1_id]
        ea = 1.0 / (1.0 + 10 ** ((rb - ra) / 400.0))
        eb = 1.0 - ea
        sa = 0.5 if winner is None else (1.0 if winner == 0 else 0.0)
        sb = 1.0 - sa
        for uid, old, s, e in ((p0_id, ra, sa, ea), (p1_id, rb, sb, eb)):
            new_rating = old + _K * (s - e)
            conn.execute(
                """INSERT INTO ratings (game, user_id, rating, games, wins)
                   VALUES (?,?,?,1,?) ON CONFLICT(game, user_id) DO UPDATE SET
                   rating=excluded.rating, games=games+1,
                   wins=wins+excluded.wins""",
                (game, uid, new_rating, 1 if s == 1.0 else 0))
            conn.execute(
                "INSERT INTO rating_history (game, user_id, rating, "
                "created_at) VALUES (?,?,?,?)",
                (game, uid, new_rating, time.time()))
        conn.commit()
    finally:
        conn.close()


def rating_history(game: str, user_id: int, limit: int = 50) -> list[dict]:
    """ELO after each settlement, oldest first (for the 走势 sparkline)."""
    conn = _db()
    try:
        rows = conn.execute(
            "SELECT rating, created_at FROM rating_history "
            "WHERE game = ? AND user_id = ? ORDER BY id DESC LIMIT ?",
            (game, user_id, limit)).fetchall()
    finally:
        conn.close()
    return [{"rating": r[0], "created_at": r[1]} for r in reversed(rows)]


# ------------------------------------------------------------- v2 records

def insert_v2(uid: str, game: str, kind: str, version: str | None, mode: str,
              visibility: str, clock: dict, players: list, models: list,
              status: str, created_at: float) -> int:
    conn = _db()
    try:
        cur = conn.execute(
            "INSERT INTO matches (game, kind, players, models, status, created_at, "
            "uid, mode, visibility, version, clock) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (game, kind, json.dumps(players), json.dumps(models), status, created_at,
             uid, mode, visibility, version, json.dumps(clock)))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def update_v2(row_id: int, **fields) -> None:
    """status / kind / players / models / result / finished_at / frames."""
    allowed = {"status", "kind", "players", "models", "result", "finished_at", "frames"}
    assert set(fields) <= allowed, set(fields) - allowed
    values = [json.dumps(v) if k in ("players", "models", "result") else v
              for k, v in fields.items()]
    conn = _db()
    try:
        conn.execute(f"UPDATE matches SET {', '.join(f'{k}=?' for k in fields)} WHERE id=?",
                     (*values, row_id))
        conn.commit()
    finally:
        conn.close()


def save_seats(row_id: int, seats: list[tuple[str, int | None, dict]]) -> None:
    conn = _db()
    try:
        conn.execute("DELETE FROM match_seats WHERE match_id=?", (row_id,))
        conn.executemany(
            "INSERT INTO match_seats (match_id, seat, user_id, controller) VALUES (?,?,?,?)",
            [(row_id, seat, uid, json.dumps(ctl)) for seat, uid, ctl in seats])
        conn.commit()
    finally:
        conn.close()


def get_v2(uid: str) -> dict | None:
    """One v2 match record with its seats, or None."""
    conn = _db()
    try:
        row = conn.execute(
            "SELECT id, game, kind, players, models, status, result, created_at, "
            "finished_at, uid, mode, visibility, version, clock, frames "
            "FROM matches WHERE uid=?", (uid,)).fetchone()
        if row is None:
            return None
        seats = conn.execute(
            "SELECT seat, user_id, controller FROM match_seats WHERE match_id=? "
            "ORDER BY seat", (row[0],)).fetchall()
    finally:
        conn.close()
    return {"row_id": row[0], "game": row[1], "kind": row[2],
            "players": json.loads(row[3] or "[]"), "models": json.loads(row[4] or "[]"),
            "status": row[5], "result": json.loads(row[6]) if row[6] else None,
            "created_at": row[7], "finished_at": row[8], "uid": row[9], "mode": row[10],
            "visibility": row[11], "version": row[12],
            "clock": json.loads(row[13]) if row[13] else None, "frames": row[14],
            "seats": [{"seat": s, "user_id": u, "controller": json.loads(c)}
                      for s, u, c in seats]}


def frames_path(uid: str) -> Path:
    return SCORES_DB.parent / "replays" / f"{uid}.jsonl.gz"


def write_frames(uid: str, frames: list[dict]) -> str:
    """Seal a finished match's frames: one JSON object per line, gzip."""
    path = frames_path(uid)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as fh:
        for frame in frames:
            fh.write(json.dumps(frame, ensure_ascii=False, separators=(",", ":")) + "\n")
    tmp.replace(path)
    return str(path)


def read_frames(path: str) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def abort_unfinished_v2(cause: str = "server_restart") -> int:
    """Live v2 matches exist only in memory (D12): on boot they are gone, so
    their rows become aborted instead of silently disappearing."""
    conn = _db()
    try:
        cur = conn.execute(
            "UPDATE matches SET status='aborted', result=?, finished_at=? "
            "WHERE uid IS NOT NULL AND status IN ('waiting', 'active')",
            (json.dumps({"winner": None, "cause": cause}), time.time()))
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


# ------------------------------------------------------------------ history

def get_match(match_id: int) -> dict | None:
    conn = _db()
    try:
        cur = conn.execute("SELECT * FROM matches WHERE id=?", (match_id,))
        row = cur.fetchone()
        columns = [d[0] for d in cur.description] if cur.description else None
    finally:
        conn.close()
    return _row(row, columns) if row else None


def top_ratings(game: str, limit: int = 20) -> list[dict]:
    conn = _db()
    try:
        rows = conn.execute(
            """SELECT r.user_id, r.rating, r.games, r.wins, u.nickname, u.username
               FROM ratings r LEFT JOIN users u ON u.id = r.user_id
               WHERE r.game = ? ORDER BY r.rating DESC LIMIT ?""",
            (game, limit)).fetchall()
    finally:
        conn.close()
    return [{"user_id": r[0], "rating": round(r[1], 1), "games": r[2],
             "wins": r[3], "name": r[5] or r[4] or f"user-{r[0]}"}
            for r in rows]


def list_matches(user_id: int) -> list[dict]:
    """Matches where the user played (v2 seats are projected into players)."""
    conn = _db()
    try:
        cur = conn.execute(
            "SELECT * FROM matches WHERE status != 'queued' ORDER BY id DESC "
            "LIMIT 200")
        rows = cur.fetchall()
        columns = [d[0] for d in cur.description] if cur.description else None
    finally:
        conn.close()
    out = []
    for r in rows:
        m = _row(r, columns)
        if any(p.get("user_id") == user_id for p in m["players"]):
            out.append(m)
    return out
