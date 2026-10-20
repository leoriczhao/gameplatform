"""Operations (v1.0-d): announcements, reports, admin console, dashboard.

- First admin bootstrapped from ADMIN_USERNAME/ADMIN_PASSWORD at startup
- Ban = users.status='banned' (auth.login_user already rejects non-active)
- Model takedown = models.status='banned' (every consumer checks active)
- DAU proxy: distinct users with xp_events in the last 24h (every game
  finish awards XP) + in-memory active sessions
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path

import auth
import sessions

SCORES_DB = Path(os.environ.get("SCORES_DB", "/data/scores.db"))
DAY = 24 * 3600


def _db() -> sqlite3.Connection:
    SCORES_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(SCORES_DB, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS announcements (
               id INTEGER PRIMARY KEY AUTOINCREMENT, body TEXT NOT NULL,
               active INTEGER DEFAULT 1, created_at REAL NOT NULL)""")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS reports (
               id INTEGER PRIMARY KEY AUTOINCREMENT, reporter_id INTEGER NOT NULL,
               target_type TEXT NOT NULL, target_id INTEGER NOT NULL,
               reason TEXT, status TEXT DEFAULT 'open',
               created_at REAL NOT NULL)""")
    return conn


# ------------------------------------------------------------ admin bootstrap

def bootstrap_admin() -> bool:
    """Create/ensure the first admin from ADMIN_USERNAME/ADMIN_PASSWORD.
    Returns True if an admin was created (new user) or already existed."""
    username = os.environ.get("ADMIN_USERNAME", "").strip()
    password = os.environ.get("ADMIN_PASSWORD", "")
    if not username or not password:
        return False
    auth._db().close()  # ensure the users table exists (idempotent)
    conn = _db()
    try:
        row = conn.execute("SELECT id FROM users WHERE username = ?",
                           (username,)).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO users (username, password_hash, nickname, role, "
                "status, created_at, avatar, signature, xp) "
                "VALUES (?,?,?,?,?,?,?,?,0)",
                (username, auth.hash_password(password), username, "admin",
                 "active", time.time(), "🛡️", "平台管理员"))
            conn.commit()
        else:
            conn.execute("UPDATE users SET role = 'admin' WHERE id = ?",
                         (row[0],))
            conn.commit()
    finally:
        conn.close()
    return True


# --------------------------------------------------------------- announcements

def list_announcements(active_only: bool = True) -> list[dict]:
    conn = _db()
    try:
        sql = "SELECT id, body, active, created_at FROM announcements"
        if active_only:
            sql += " WHERE active = 1"
        rows = conn.execute(sql + " ORDER BY id DESC LIMIT 20").fetchall()
    finally:
        conn.close()
    return [{"id": r[0], "body": r[1], "active": bool(r[2]),
             "created_at": r[3]} for r in rows]


def create_announcement(body: str) -> dict:
    body = " ".join(body.split())[:300]
    if not body:
        raise ValueError("公告内容不能为空")
    conn = _db()
    try:
        cur = conn.execute(
            "INSERT INTO announcements (body, active, created_at) "
            "VALUES (?,1,?)", (body, time.time()))
        conn.commit()
        aid = cur.lastrowid
    finally:
        conn.close()
    return {"id": aid, "body": body, "active": True,
            "created_at": time.time()}


def set_announcement_active(aid: int, active: bool) -> bool:
    conn = _db()
    try:
        cur = conn.execute("UPDATE announcements SET active = ? WHERE id = ?",
                           (1 if active else 0, aid))
        conn.commit()
    finally:
        conn.close()
    return cur.rowcount > 0
# --------------------------------------------------------------- reports

def create_report(reporter_id: int, target_type: str, target_id: int,
                  reason: str) -> dict:
    if target_type not in ("user", "model", "match", "chat",
                           "ugc_game", "ugc_version"):
        raise ValueError("target_type 必须是 user|model|match|chat|ugc_game|ugc_version")
    reason = " ".join(reason.split())[:300] if reason else ""
    conn = _db()
    try:
        cur = conn.execute(
            "INSERT INTO reports (reporter_id, target_type, target_id, reason, "
            "status, created_at) VALUES (?,?,?,?,?,?)",
            (reporter_id, target_type, target_id, reason, "open", time.time()))
        conn.commit()
        rid = cur.lastrowid
    finally:
        conn.close()
    return {"id": rid, "target_type": target_type, "target_id": target_id,
            "reason": reason, "status": "open", "created_at": time.time()}


def list_reports(status: str | None = None) -> list[dict]:
    conn = _db()
    try:
        sql = ("SELECT r.id, r.reporter_id, r.target_type, r.target_id, "
               "r.reason, r.status, r.created_at, u.username, u.nickname "
               "FROM reports r LEFT JOIN users u ON u.id = r.reporter_id")
        args: tuple = ()
        if status:
            sql += " WHERE r.status = ?"
            args = (status,)
        rows = conn.execute(sql + " ORDER BY r.id DESC LIMIT 100", args).fetchall()
    finally:
        conn.close()
    return [{"id": r[0], "reporter_id": r[1], "target_type": r[2],
             "target_id": r[3], "reason": r[4], "status": r[5],
             "created_at": r[6], "reporter": r[8] or r[7]} for r in rows]


def set_report_status(rid: int, status: str) -> bool:
    if status not in ("open", "resolved", "dismissed"):
        raise ValueError("status 必须是 open|resolved|dismissed")
    conn = _db()
    try:
        cur = conn.execute("UPDATE reports SET status = ? WHERE id = ?",
                           (status, rid))
        conn.commit()
    finally:
        conn.close()
    return cur.rowcount > 0
# ------------------------------------------------------------- admin console

def list_users() -> list[dict]:
    conn = _db()
    try:
        rows = conn.execute(
            "SELECT id, username, nickname, role, status, xp, created_at "
            "FROM users ORDER BY id DESC LIMIT 200").fetchall()
    finally:
        conn.close()
    return [{"id": r[0], "username": r[1], "nickname": r[2] or r[1],
             "role": r[3], "status": r[4], "xp": int(r[5] or 0),
             "created_at": r[6]} for r in rows]


def set_user_status(user_id: int, status: str, by_admin_id: int) -> bool:
    """Ban/unban. Admins cannot be banned; you cannot ban yourself.
    Banning also takes down the user's UGC games (design 10 §8)."""
    if status not in ("active", "banned"):
        raise ValueError("status 必须是 active|banned")
    if user_id == by_admin_id:
        raise ValueError("不能封禁自己")
    conn = _db()
    try:
        row = conn.execute("SELECT role FROM users WHERE id = ?",
                           (user_id,)).fetchone()
        if row is None:
            raise KeyError("用户不存在")
        if row[0] == "admin":
            raise ValueError("不能封禁管理员")
        cur = conn.execute("UPDATE users SET status = ? WHERE id = ?",
                           (status, user_id))
        conn.commit()
    finally:
        conn.close()
    if status == "banned":
        import ugc
        try:
            ugc.ban_user_games(user_id)
        except Exception:
            pass   # UGC 联动失败不影响封禁本身
    return cur.rowcount > 0


def list_models_all() -> list[dict]:
    conn = _db()
    try:
        rows = conn.execute(
            "SELECT m.id, m.owner_id, m.game, m.name, m.io_contract, m.status, "
            "m.created_at, u.username, u.nickname FROM models m "
            "LEFT JOIN users u ON u.id = m.owner_id ORDER BY m.id DESC "
            "LIMIT 200").fetchall()
    finally:
        conn.close()
    return [{"id": r[0], "owner_id": r[1], "game": r[2], "name": r[3],
             "contract": r[4], "status": r[5], "created_at": r[6],
             "owner": r[8] or r[7] or f"user-{r[1]}"} for r in rows]


def set_model_status(model_id: int, status: str) -> bool:
    """Takedown (banned) / restore (active)."""
    if status not in ("active", "banned"):
        raise ValueError("status 必须是 active|banned")
    conn = _db()
    try:
        cur = conn.execute("UPDATE models SET status = ? WHERE id = ?",
                           (status, model_id))
        conn.commit()
    finally:
        conn.close()
    return cur.rowcount > 0


def list_matches_all(limit: int = 50) -> list[dict]:
    conn = _db()
    try:
        rows = conn.execute(
            "SELECT id, game, kind, players, models, status, result, "
            "created_at, finished_at FROM matches ORDER BY id DESC LIMIT ?",
            (limit,)).fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        out.append({
            "id": r[0], "game": r[1], "kind": r[2],
            "players": json.loads(r[3] or "[]"),
            "models": json.loads(r[4] or "[]"),
            "status": r[5],
            "result": json.loads(r[6]) if r[6] else None,
            "created_at": r[7], "finished_at": r[8],
        })
    return out
def dashboard() -> dict:
    # ensure sibling schemas exist before aggregating (idempotent)
    import growth
    import matches as match_store
    import models as model_store
    growth.ensure_schema()
    match_store._db().close()
    model_store._db().close()
    now = time.time()
    cutoff = now - DAY
    conn = _db()
    try:
        users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        new_users = conn.execute(
            "SELECT COUNT(*) FROM users WHERE created_at >= ?",
            (cutoff,)).fetchone()[0]
        matches_total = conn.execute(
            "SELECT COUNT(*) FROM matches WHERE kind='pvp' AND status='finished'",
        ).fetchone()[0]
        matches_day = conn.execute(
            "SELECT COUNT(*) FROM matches WHERE status='finished' AND "
            "finished_at >= ?", (cutoff,)).fetchone()[0]
        models = conn.execute(
            "SELECT COUNT(*) FROM models WHERE status != 'deleted'",
        ).fetchone()[0]
        dau = conn.execute(
            "SELECT COUNT(DISTINCT user_id) FROM xp_events WHERE created_at >= ?",
            (cutoff,)).fetchone()[0]
        reports_open = conn.execute(
            "SELECT COUNT(*) FROM reports WHERE status='open'",
        ).fetchone()[0]
    finally:
        conn.close()
    return {
        "users_total": int(users),
        "users_new_24h": int(new_users),
        "dau_24h": int(dau),
        "active_sessions": sessions.active_session_count(),
        "matches_total": int(matches_total),
        "matches_24h": int(matches_day),
        "models_active": int(models),
        "reports_open": int(reports_open),
        "time": now,
    }






