"""Social services (v1.0-b): profile, friends, room chat, notifications.

Design: docs/design/00 模块 B/G；D14 聊天/通知走轮询 + 落库（SQLite，D15）。
- friends: symmetric (直接加，无需同意；互见)
- chat: per-PvP-session messages, participants only, since-cursor polling
- notifications: stored rows with read flag; the bell polls unread count
"""
from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path

import growth

SCORES_DB = Path(os.environ.get("SCORES_DB", "/data/scores.db"))
CHAT_PAGE = 200   # max messages returned per poll
NOTIF_PAGE = 100


def _db() -> sqlite3.Connection:
    SCORES_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(SCORES_DB, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS friends (
               user_id INTEGER NOT NULL, friend_id INTEGER NOT NULL,
               created_at REAL NOT NULL,
               PRIMARY KEY (user_id, friend_id))""")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS chat_messages (
               id INTEGER PRIMARY KEY AUTOINCREMENT, room_id TEXT NOT NULL,
               user_id INTEGER NOT NULL, nickname TEXT, text TEXT NOT NULL,
               created_at REAL NOT NULL)""")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_chat_room ON chat_messages(room_id, id)")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS notifications (
               id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
               kind TEXT NOT NULL, body TEXT NOT NULL, link TEXT,
               read INTEGER DEFAULT 0, created_at REAL NOT NULL)""")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_notif_user ON notifications(user_id, id)")
    return conn


def _user_row(conn, user_id: int):
    return conn.execute(
        "SELECT id, username, nickname, avatar, signature, role, status, "
        "created_at, xp FROM users WHERE id = ?", (user_id,)).fetchone()


def _to_user(row) -> dict:
    xp = int(row[8] or 0)
    return {"id": row[0], "username": row[1],
            "nickname": row[2] or row[1], "avatar": row[3] or "",
            "signature": row[4] or "", "role": row[5],
            "status": row[6], "created_at": row[7],
            "xp": xp, "level": growth.level_of(xp),
            "level_progress": growth.level_progress(xp)}
# ---------------------------------------------------------------- profile

def get_profile(user_id: int) -> dict | None:
    conn = _db()
    try:
        row = _user_row(conn, user_id)
    finally:
        conn.close()
    return _to_user(row) if row else None


def update_profile(user_id: int, nickname: str | None, avatar: str | None,
                   signature: str | None) -> dict:
    """Partial update; raises ValueError on invalid input."""
    if nickname is not None:
        nickname = " ".join(nickname.split())[:24]
        if not (1 <= len(nickname) <= 24):
            raise ValueError("昵称需 1-24 字符")
    if avatar is not None:
        avatar = avatar.strip()[:16]
        if not avatar:
            raise ValueError("头像不能为空")
    if signature is not None:
        signature = signature.strip()[:120]
    conn = _db()
    try:
        sets, args = [], []
        for col, val in (("nickname", nickname), ("avatar", avatar),
                         ("signature", signature)):
            if val is not None:
                sets.append(f"{col} = ?")
                args.append(val)
        if sets:
            args.append(user_id)
            conn.execute(f"UPDATE users SET {', '.join(sets)} WHERE id = ?",
                         args)
            conn.commit()
        row = _user_row(conn, user_id)
    finally:
        conn.close()
    return _to_user(row)


# ---------------------------------------------------------------- friends

def list_friends(user_id: int) -> list[dict]:
    conn = _db()
    try:
        rows = conn.execute(
            """SELECT u.id, u.username, u.nickname, u.avatar, u.signature,
               u.role, u.status, u.created_at, u.xp
               FROM friends f JOIN users u ON u.id = f.friend_id
               WHERE f.user_id = ? ORDER BY f.created_at DESC""",
            (user_id,)).fetchall()
    finally:
        conn.close()
    return [_to_user(r) for r in rows]


def add_friend(user_id: int, username: str) -> dict:
    """Add by username; symmetric (both directions), no consent (v1).
    Raises ValueError / KeyError."""
    conn = _db()
    try:
        row = conn.execute(
            "SELECT id FROM users WHERE username = ?", (username.strip(),)
        ).fetchone()
        if row is None:
            raise KeyError("用户不存在")
        fid = row[0]
        if fid == user_id:
            raise ValueError("不能添加自己为好友")
        exists = conn.execute(
            "SELECT 1 FROM friends WHERE user_id=? AND friend_id=?",
            (user_id, fid)).fetchone()
        if exists:
            raise ValueError("已经是好友")
        now = time.time()
        conn.execute(
            "INSERT INTO friends (user_id, friend_id, created_at) VALUES (?,?,?)",
            (user_id, fid, now))
        conn.execute(
            "INSERT INTO friends (user_id, friend_id, created_at) VALUES (?,?,?)",
            (fid, user_id, now))
        conn.execute(
            "INSERT INTO notifications (user_id, kind, body, link, read, "
            "created_at) VALUES (?,?,?,?,0,?)",
            (fid, "friend_add",
             f"{_nickname(conn, user_id)} 添加你为好友", "/friends", now))
        conn.commit()
        friend = _user_row(conn, fid)
    finally:
        conn.close()
    return _to_user(friend)


def _nickname(conn, user_id: int) -> str:
    row = conn.execute(
        "SELECT nickname, username FROM users WHERE id = ?", (user_id,)).fetchone()
    return (row[0] or row[1]) if row else "?"


def remove_friend(user_id: int, friend_id: int) -> bool:
    conn = _db()
    try:
        cur = conn.execute(
            "DELETE FROM friends WHERE (user_id=? AND friend_id=?) OR "
            "(user_id=? AND friend_id=?)",
            (user_id, friend_id, friend_id, user_id))
        conn.commit()
    finally:
        conn.close()
    return cur.rowcount > 0
# ------------------------------------------------------------------- chat

def chat_send(room_id: str, user_id: int, text: str) -> dict:
    text = " ".join(text.split())[:500]
    if not text:
        raise ValueError("消息不能为空")
    conn = _db()
    try:
        row = conn.execute(
            "SELECT nickname, username FROM users WHERE id = ?",
            (user_id,)).fetchone()
        nickname = (row[0] or row[1]) if row else f"user-{user_id}"
        now = time.time()
        cur = conn.execute(
            "INSERT INTO chat_messages (room_id, user_id, nickname, text, "
            "created_at) VALUES (?,?,?,?,?)",
            (room_id, user_id, nickname, text, now))
        conn.commit()
        msg_id = cur.lastrowid
    finally:
        conn.close()
    return {"id": msg_id, "room_id": room_id, "user_id": user_id,
            "nickname": nickname, "text": text, "created_at": now}


def chat_since(room_id: str, since: int = 0) -> tuple[list[dict], int]:
    """Messages after `since` (id cursor), oldest first, capped."""
    conn = _db()
    try:
        rows = conn.execute(
            "SELECT id, room_id, user_id, nickname, text, created_at "
            "FROM chat_messages WHERE room_id = ? AND id > ? "
            "ORDER BY id ASC LIMIT ?",
            (room_id, since, CHAT_PAGE)).fetchall()
    finally:
        conn.close()
    msgs = [{"id": r[0], "room_id": r[1], "user_id": r[2],
             "nickname": r[3], "text": r[4], "created_at": r[5]}
            for r in rows]
    next_since = msgs[-1]["id"] if msgs else since
    return msgs, next_since


# ----------------------------------------------------------- notifications


def list_notifications(user_id: int) -> list[dict]:
    conn = _db()
    try:
        rows = conn.execute(
            "SELECT id, kind, body, link, read, created_at FROM notifications "
            "WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, NOTIF_PAGE)).fetchall()
    finally:
        conn.close()
    return [{"id": r[0], "kind": r[1], "body": r[2], "link": r[3],
             "read": bool(r[4]), "created_at": r[5]} for r in rows]


def unread_count(user_id: int) -> int:
    conn = _db()
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM notifications WHERE user_id = ? AND read = 0",
            (user_id,)).fetchone()
    finally:
        conn.close()
    return int(row[0])


def mark_all_read(user_id: int) -> None:
    conn = _db()
    try:
        conn.execute("UPDATE notifications SET read = 1 WHERE user_id = ?",
                     (user_id,))
        conn.commit()
    finally:
        conn.close()



