"""Generic leaderboard service — one SQLite table with a game_id column.

Same semantics as the original snake service: score desc, earliest first on
ties, prune to the top 5000 per game.
"""
from __future__ import annotations

import os
import re
import sqlite3
import time
from pathlib import Path

SCORES_DB = Path(os.environ.get("SCORES_DB", "/data/scores.db"))


def _db() -> sqlite3.Connection:
    SCORES_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(SCORES_DB, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS scores (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               game_id TEXT NOT NULL,
               name TEXT NOT NULL,
               score INTEGER NOT NULL,
               mode TEXT NOT NULL DEFAULT 'human',
               user_id INTEGER,
               match_id INTEGER,
               created_at REAL NOT NULL
           )"""
    )
    # 轻量迁移：老库补列（历史行为 NULL；新行由服务端权威对局写入）
    cols = {row[1] for row in conn.execute("PRAGMA table_info(scores)")}
    if "user_id" not in cols:
        conn.execute("ALTER TABLE scores ADD COLUMN user_id INTEGER")
    if "match_id" not in cols:
        conn.execute("ALTER TABLE scores ADD COLUMN match_id INTEGER")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_scores_game "
                 "ON scores (game_id, score DESC, created_at ASC)")
    # 同一场对局只能上榜一次（SQLite 唯一索引允许多个 NULL 历史行）
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_scores_match "
                 "ON scores (match_id)")
    return conn


def _prune(conn: sqlite3.Connection, game_id: str, keep: int = 5000) -> None:
    conn.execute(
        """DELETE FROM scores WHERE game_id = ? AND id NOT IN
           (SELECT id FROM scores WHERE game_id = ?
            ORDER BY score DESC, created_at ASC LIMIT ?)""",
        (game_id, game_id, keep),
    )
    conn.commit()


def top(game_id: str, limit: int = 10) -> list[dict]:
    conn = _db()
    try:
        rows = conn.execute(
            "SELECT name, score, mode, created_at FROM scores "
            "WHERE game_id = ? ORDER BY score DESC, created_at ASC LIMIT ?",
            (game_id, limit),
        ).fetchall()
    finally:
        conn.close()
    return [
        {"rank": i + 1, "name": name, "score": score, "mode": mode,
         "created_at": created_at}
        for i, (name, score, mode, created_at) in enumerate(rows)
    ]


def submit(game_id: str, name: str, score: int, mode: str,
           user_id: int | None = None,
           match_id: int | None = None) -> dict:
    name = re.sub(r"\s+", " ", name.strip())
    if not name:
        raise ValueError("name is empty")
    conn = _db()
    try:
        if match_id is not None:
            row = conn.execute("SELECT id FROM scores WHERE match_id = ?",
                               (match_id,)).fetchone()
            if row is not None:
                raise ValueError("该对局已经上过榜")
        try:
            cur = conn.execute(
                "INSERT INTO scores (game_id, name, score, mode, user_id, "
                "match_id, created_at) VALUES (?,?,?,?,?,?,?)",
                (game_id, name[:24], score, mode or "human", user_id,
                 match_id, time.time()),
            )
        except sqlite3.IntegrityError:
            raise ValueError("该对局已经上过榜")
        conn.commit()
        score_id = cur.lastrowid
        rank = conn.execute(
            """SELECT COUNT(*) + 1 FROM scores WHERE game_id = ?
               AND (score > ? OR (score = ? AND created_at <
               (SELECT created_at FROM scores WHERE id = ?)))""",
            (game_id, score, score, score_id),
        ).fetchone()[0]
        _prune(conn, game_id)
    finally:
        conn.close()
    return {"id": score_id, "rank": rank, "name": name[:24],
            "score": score, "mode": mode or "human", "match_id": match_id}
