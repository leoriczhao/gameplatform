"""Account service — users, password hashing, JWT, guests.

Design: docs/design/02-账号体系.md

- users stored in the same SQLite file as scores (SCORES_DB)
- passwords hashed with bcrypt (cost 12)
- JWT (HS256) with the platform secret persisted at /data/secret.key so
  tokens survive container restarts
"""
from __future__ import annotations

import os
import re
import secrets
import sqlite3
import time
from pathlib import Path

import bcrypt
import jwt

SCORES_DB = Path(os.environ.get("SCORES_DB", "/data/scores.db"))
TOKEN_TTL_USER = 7 * 24 * 3600   # 7 days
TOKEN_TTL_GUEST = 12 * 3600      # 12 hours

USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]{3,24}$")


def _db() -> sqlite3.Connection:
    SCORES_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(SCORES_DB, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS users (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               username TEXT NOT NULL UNIQUE,
               password_hash TEXT NOT NULL,
               nickname TEXT,
               role TEXT NOT NULL DEFAULT 'user',
               status TEXT NOT NULL DEFAULT 'active',
               created_at REAL NOT NULL,
               avatar TEXT,
               signature TEXT,
               xp INTEGER DEFAULT 0
           )"""
    )
    # v1.0-b/c migration: add columns to pre-existing databases
    for col, typ in (("avatar", "TEXT"), ("signature", "TEXT"),
                     ("xp", "INTEGER")):
        try:
            conn.execute(f"ALTER TABLE users ADD COLUMN {col} {typ}")
        except sqlite3.OperationalError:
            pass  # column already exists
    return conn


def _secret() -> str:
    """Load or create the JWT secret (persisted so tokens survive restarts)."""
    p = SCORES_DB.parent / "secret.key"
    if not p.exists():
        p.write_text(secrets.token_hex(32))
        p.chmod(0o600)
    return p.read_text().strip()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


def create_token(sub: str, role: str, ttl: int) -> str:
    now = int(time.time())
    return jwt.encode(
        {"sub": str(sub), "role": role, "iat": now, "exp": now + ttl},
        _secret(), algorithm="HS256")


def decode_token(token: str) -> dict | None:
    """Payload dict on success, None on any failure."""
    try:
        return jwt.decode(token, _secret(), algorithms=["HS256"])
    except jwt.PyJWTError:
        return None


def _row_to_user(row) -> dict:
    return {"id": row[0], "username": row[1],
            "nickname": row[3] or row[1], "role": row[4],
            "status": row[5], "created_at": row[6]}


def register_user(username: str, password: str) -> tuple[dict, str]:
    """Create a user; raises ValueError on bad input/duplicate."""
    username = username.strip()
    if not USERNAME_RE.match(username):
        raise ValueError("用户名需 3-24 位字母/数字/下划线")
    if len(password) < 8:
        raise ValueError("密码至少 8 位")
    conn = _db()
    try:
        try:
            cur = conn.execute(
                "INSERT INTO users (username, password_hash, nickname, role, "
                "status, created_at) VALUES (?,?,?,?,?,?)",
                (username, hash_password(password), username, "user",
                 "active", time.time()))
            conn.commit()
        except sqlite3.IntegrityError:
            raise ValueError("用户名已被注册")
        user = user_by_id(cur.lastrowid)
    finally:
        conn.close()
    return user, create_token(str(user["id"]), user["role"], TOKEN_TTL_USER)


def login_user(username: str, password: str) -> tuple[dict, str] | None:
    conn = _db()
    try:
        row = conn.execute(
            "SELECT id, username, password_hash, nickname, role, status, "
            "created_at FROM users WHERE username = ?",
            (username.strip(),)).fetchone()
    finally:
        conn.close()
    if row is None or not verify_password(password, row[2]):
        return None
    if row[5] != "active":
        return None
    user = _row_to_user(row)
    return user, create_token(str(user["id"]), user["role"], TOKEN_TTL_USER)


def user_by_id(user_id: int) -> dict | None:
    conn = _db()
    try:
        row = conn.execute(
            "SELECT id, username, password_hash, nickname, role, status, "
            "created_at FROM users WHERE id = ?", (user_id,)).fetchone()
    finally:
        conn.close()
    return _row_to_user(row) if row else None


def official_author_id() -> int:
    """Non-login system author; bootstrapping games requires no admin password."""
    conn = _db()
    try:
        # ':' is not accepted by register_user, so users cannot claim this name.
        conn.execute(
            "INSERT OR IGNORE INTO users (username,password_hash,nickname,role,status,created_at) "
            "VALUES ('system:official','!','官方','system','disabled',?)", (time.time(),))
        conn.commit()
        return conn.execute("SELECT id FROM users WHERE username='system:official'").fetchone()[0]
    finally:
        conn.close()


def guest_principal(request) -> dict:
    """Guest identity (anonymous, limited access); display only."""
    ip = (request.headers.get("x-forwarded-for", "") or
          (request.client.host if request.client else "?")).split(",")[0].strip()
    return {"id": None, "username": f"guest-{ip}", "nickname": "游客",
            "role": "guest", "status": "active"}


def principal_from_request(request) -> dict:
    """Resolve the caller: bearer token -> user or token-guest; else IP-guest.

    Guest tokens (sub="guest-<uuid>") give each browser its own identity, so
    shared NATs don't collide on per-IP session caps."""
    authz = request.headers.get("authorization", "")
    if authz.lower().startswith("bearer "):
        payload = decode_token(authz[7:].strip())
        if payload:
            sub = payload.get("sub")
            if isinstance(sub, str) and sub.isdigit():
                user = user_by_id(int(sub))
                if user and user["status"] == "active":
                    user = dict(user)
                    user["role"] = payload.get("role") or user["role"]
                    return user
            if isinstance(sub, str) and sub.startswith("guest-"):
                return {"id": None, "username": sub, "nickname": "游客",
                        "role": "guest", "status": "active"}
    return guest_principal(request)
