"""Growth & leaderboards (v1.0-c): XP/levels, rating history, stats.

Numbers: docs/design/08-成长与赛事数值.md（XP 表、等级曲线 50·n·(n-1)）。
- xp_events: append-only ledger; users.xp keeps the cached total
- rating_history: one row per ELO settlement (for the 走势 sparkline)
- stats/me + weekly board aggregate the matches table
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path

SCORES_DB = Path(os.environ.get("SCORES_DB", "/data/scores.db"))

XP_PVP_PLAY = 10
XP_PVP_WIN = 15
XP_PVE_FINISH = 5
XP_PVE_WIN = 5
HISTORY_LIMIT = 50
WEEK_SECONDS = 7 * 24 * 3600


def _db() -> sqlite3.Connection:
    SCORES_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(SCORES_DB, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS xp_events (
               id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
               game TEXT, kind TEXT NOT NULL, xp INTEGER NOT NULL,
               created_at REAL NOT NULL)""")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_xp_user ON xp_events(user_id, id)")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_xp_game_time ON xp_events(game, created_at)")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS rating_history (
               id INTEGER PRIMARY KEY AUTOINCREMENT, game TEXT NOT NULL,
               user_id INTEGER NOT NULL, rating REAL NOT NULL,
               created_at REAL NOT NULL)""")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_rh_game_user ON rating_history(game, user_id, id)")
    return conn


def ensure_schema() -> None:
    """Create growth tables (called by other modules before inserting)."""
    _db().close()


# -------------------------------------------------------------------- xp

def award_xp(user_id: int, game: str | None, kind: str, xp: int) -> int:
    """Append an xp event and bump users.xp atomically; returns the new
    total."""
    conn = _db()
    try:
        conn.execute(
            "INSERT INTO xp_events (user_id, game, kind, xp, created_at) "
            "VALUES (?,?,?,?,?)",
            (user_id, game, kind, xp, time.time()))
        conn.execute(
            "UPDATE users SET xp = COALESCE(xp, 0) + ? WHERE id = ?",
            (xp, user_id))
        conn.commit()
        row = conn.execute("SELECT xp FROM users WHERE id = ?",
                           (user_id,)).fetchone()
    finally:
        conn.close()
    return int(row[0] or 0)


def xp_of(user_id: int) -> int:
    conn = _db()
    try:
        row = conn.execute("SELECT xp FROM users WHERE id = ?",
                           (user_id,)).fetchone()
    finally:
        conn.close()
    return int(row[0] or 0) if row else 0


def level_of(xp: int) -> int:
    """Level curve: xp_for_level(n) = 50·n·(n-1)."""
    n = 1
    while 50 * (n + 1) * n <= xp:
        n += 1
    return n


def level_progress(xp: int) -> float:
    """Fraction of the way from the current level to the next (0..1)."""
    lv = level_of(xp)
    base = 50 * lv * (lv - 1)
    need = 50 * (lv + 1) * lv - base
    return min(1.0, max(0.0, (xp - base) / need)) if need else 1.0


def award_pvp(sess) -> None:
    """XP for a finished PvP session (both modes; both players)."""
    for side, pid in (("p0", sess.p0["id"]), ("p1", sess.p1["id"])):
        award_xp(pid, sess.game, "pvp_play", XP_PVP_PLAY)
        if sess.winner is not None and side == f"p{sess.winner}":
            award_xp(pid, sess.game, "pvp_win", XP_PVP_WIN)


def award_pve(sess) -> None:
    """XP for a finished PvE session (registered users only)."""
    uid = sess.principal.get("id") if sess.principal else None
    if not uid:
        return
    award_xp(uid, sess.game, "pve_finish", XP_PVE_FINISH)
    if sess.winner == 0:
        award_xp(uid, sess.game, "pve_win", XP_PVE_WIN)


# --------------------------------------------------------- rating history


def rating_history(game: str, user_id: int, limit: int = HISTORY_LIMIT) -> list[dict]:
    conn = _db()
    try:
        rows = conn.execute(
            "SELECT rating, created_at FROM rating_history "
            "WHERE game = ? AND user_id = ? ORDER BY id DESC LIMIT ?",
            (game, user_id, limit)).fetchall()
    finally:
        conn.close()
    return [{"rating": r[0], "created_at": r[1]} for r in reversed(rows)]
# ------------------------------------------------------------- stats / boards

def _my_pvp_matches(user_id: int) -> list[dict]:
    """Finished PvP matches where the user played, oldest first."""
    conn = _db()
    try:
        rows = conn.execute(
            "SELECT id, game, players, result, created_at, finished_at "
            "FROM matches WHERE kind = 'pvp' AND status = 'finished' "
            "ORDER BY id ASC").fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        players = json.loads(r[2] or "[]")
        result = json.loads(r[3]) if r[3] else {}
        sides = [p for p in players if p.get("user_id") == user_id]
        if not sides:
            continue
        side = sides[0].get("side")
        winner = result.get("winner")
        won = None if winner is None else (f"p{winner}" == side)
        out.append({"id": r[0], "game": r[1], "side": side,
                    "won": won, "result": result,
                    "created_at": r[4], "finished_at": r[5] or r[4]})
    return out


def stats_for(user_id: int) -> dict:
    ms = _my_pvp_matches(user_id)
    games = len(ms)
    wins = sum(1 for m in ms if m["won"] is True)
    losses = sum(1 for m in ms if m["won"] is False)
    draws = sum(1 for m in ms if m["won"] is None)
    play_seconds = int(sum(max(0, m["finished_at"] - m["created_at"])
                            for m in ms))
    # streaks (ordered oldest first already)
    current = best = run = 0
    for m in ms:
        if m["won"] is True:
            run += 1
            best = max(best, run)
        else:
            run = 0
    current = run
    per_game = {}
    for m in ms:
        g = per_game.setdefault(m["game"], {"games": 0, "wins": 0})
        g["games"] += 1
        if m["won"] is True:
            g["wins"] += 1
    conn = _db()
    try:
        for game in per_game:
            row = conn.execute(
                "SELECT rating FROM ratings WHERE game=? AND user_id=?",
                (game, user_id)).fetchone()
            per_game[game]["rating"] = row[0] if row else 1200.0
    finally:
        conn.close()
    for game in per_game:
        per_game[game]["history"] = rating_history(game, user_id)
    xp = xp_of(user_id)
    return {
        "xp": xp, "level": level_of(xp),
        "level_progress": level_progress(xp),
        "totals": {"games": games, "wins": wins, "losses": losses,
                     "draws": draws,
                     "win_rate": round(wins / games, 3) if games else 0.0,
                     "current_streak": current, "best_streak": best,
                     "play_seconds": play_seconds},
        "games": per_game,
    }


def total_board(game: str, limit: int = 50) -> list[dict]:
    """ELO board (existing ratings table)."""
    conn = _db()
    try:
        rows = conn.execute(
            """SELECT r.user_id, r.rating, r.games, r.wins, u.nickname,
               u.username FROM ratings r LEFT JOIN users u ON u.id = r.user_id
               WHERE r.game = ? ORDER BY r.rating DESC LIMIT ?""",
            (game, limit)).fetchall()
    finally:
        conn.close()
    return [{"user_id": r[0], "rating": round(r[1], 1), "games": r[2],
             "wins": r[3], "name": r[5] or r[4] or f"user-{r[0]}"}
            for r in rows]


def weekly_board(game: str, days: int = 7, limit: int = 50) -> list[dict]:
    """Last-N-days aggregation: rank by wins, then games, then xp (08 §3)."""
    cutoff = time.time() - days * 24 * 3600
    conn = _db()
    try:
        rows = conn.execute(
            "SELECT players, result FROM matches WHERE kind = 'pvp' "
            "AND status = 'finished' AND game = ? AND finished_at >= ?",
            (game, cutoff)).fetchall()
        xp_rows = conn.execute(
            "SELECT user_id, SUM(xp) FROM xp_events "
            "WHERE game = ? AND created_at >= ? GROUP BY user_id",
            (game, cutoff)).fetchall()
        name_rows = conn.execute(
            "SELECT id, nickname, username FROM users").fetchall()
    finally:
        conn.close()
    names = {r[0]: (r[1] or r[2]) for r in name_rows}
    agg = {}
    for players_raw, result_raw in rows:
        players = json.loads(players_raw or "[]")
        result = json.loads(result_raw) if result_raw else {}
        winner = result.get("winner")
        for p in players:
            uid = p.get("user_id")
            if uid is None:
                continue
            a = agg.setdefault(uid, {"games": 0, "wins": 0})
            a["games"] += 1
            if winner is not None and p.get("side") == f"p{winner}":
                a["wins"] += 1
    for uid, xp in xp_rows:
        agg.setdefault(uid, {"games": 0, "wins": 0})["xp"] = int(xp or 0)
    items = [{"user_id": uid, "name": names.get(uid, f"user-{uid}"),
              "games": v.get("games", 0), "wins": v.get("wins", 0),
              "xp": v.get("xp", 0)}
             for uid, v in agg.items()]
    items.sort(key=lambda x: (-x["wins"], -x["games"], -x["xp"]))
    return items[:limit]


