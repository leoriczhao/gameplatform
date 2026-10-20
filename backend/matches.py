"""Match records, ELO ratings, and the async model-vs-model match worker.

Design: docs/design/03 + 04.

- Every finished PvP session is recorded as a match and updates both players'
  ratings (ELO, K=32, start 1200) — only for registered users.
- Model-vs-model matches run in a background worker pool; the result and
  replay are stored for later viewing.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

import growth
import inference
import models as model_store
from registry import GAMES, resolve

SCORES_DB = Path(__import__("os").environ.get("SCORES_DB", "/data/scores.db"))

MATCH_STEP_CAP = 1500
MATCH_WORKER_LIMIT = threading.BoundedSemaphore(8)
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
               kind TEXT NOT NULL,           -- pvp | model_vs_model
               players TEXT NOT NULL,        -- JSON [{user_id, name, side}]
               models TEXT NOT NULL DEFAULT '[]',  -- JSON [model_id, ...]
               status TEXT NOT NULL,         -- queued | running | finished | failed
               result TEXT,                  -- JSON {winner, cause, damage}
               replay TEXT,                  -- JSON moves
               created_at REAL NOT NULL,
               finished_at REAL
           )"""
    )
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
    return conn


def _row(row) -> dict:
    return {"id": row[0], "game": row[1], "kind": row[2],
            "players": json.loads(row[3] or "[]"),
            "models": json.loads(row[4] or "[]"),
            "status": row[5],
            "result": json.loads(row[6]) if row[6] else None,
            "replay": json.loads(row[7]) if row[7] else None,
            "created_at": row[8], "finished_at": row[9]}


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
    growth.ensure_schema()   # rating_history lives in the growth schema
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


# ----------------------------------------------------------------- records

def record_pvp_finish(sess) -> int:
    """Store a finished PvP session as a match; update ratings.

    casual rooms are recorded but do NOT touch ELO (D10); ranked rooms
    update both players' ratings as before."""
    players = [
        {"user_id": sess.p0["id"], "name": sess.p0["nickname"] or sess.p0["username"],
         "side": "p0"},
        {"user_id": sess.p1["id"], "name": sess.p1["nickname"] or sess.p1["username"],
         "side": "p1"},
    ]
    result = {"winner": sess.winner, "cause": sess.cause,
              "damage": sess.state.get("damage", [0, 0]),
              "mode": getattr(sess, "mode", "ranked")}
    # replay carries the map seed so the replay viewer can rebuild every
    # state locally from the moves via the env API (07 M4 note)
    seed = sess.seed
    replay = {"schema_version": 1,
              "game_version": getattr(sess, "game_version", None),
              "seed": seed,
              "options": getattr(sess, "env_options", None),
              "moves": sess.moves}
    conn = _db()
    try:
        cur = conn.execute(
            "INSERT INTO matches (game, kind, players, models, status, result, "
            "replay, created_at, finished_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (sess.game, "pvp", json.dumps(players), "[]", "finished",
             json.dumps(result), json.dumps(replay),
             sess.created_at, time.time()))
        conn.commit()
        match_id = cur.lastrowid
    finally:
        conn.close()
    if getattr(sess, "mode", "ranked") == "ranked":
        update_ratings(sess.game, sess.p0["id"], sess.p1["id"], sess.winner)
    # XP for both players regardless of mode (08 §1; per-session idempotent)
    if not getattr(sess, "_xp_awarded", False):
        growth.award_pvp(sess)
        sess._xp_awarded = True
    return match_id


def record_pve_finish(sess) -> int | None:
    """Store a finished PvE session as a match (kind=pve, 11 P4).

    Registered users only: a guest has no account to attach the history to.
    No ELO (PvE is single-player); XP is awarded separately in step_session.
    The replay keeps seed + moves so the viewer rebuilds every state locally."""
    uid = sess.principal.get("id") if sess.principal else None
    if not uid:
        return None
    players = [{"user_id": uid,
                "name": sess.principal.get("nickname")
                        or sess.principal.get("username"),
                "side": "p0"}]
    result = {"winner": sess.winner, "cause": sess.cause,
              "controller": bool(getattr(sess, "controller", None))}
    if isinstance(sess.state, dict) and "score" in sess.state:
        result["score"] = sess.state["score"]
    seed = sess.seed
    replay = {"schema_version": 1,
              "game_version": getattr(sess, "game_version", None),
              "seed": seed,
              "options": getattr(sess, "env_options", None),
              "moves": sess.moves}
    conn = _db()
    try:
        cur = conn.execute(
            "INSERT INTO matches (game, kind, players, models, status, result, "
            "replay, created_at, finished_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (sess.game, "pve", json.dumps(players), "[]", "finished",
             json.dumps(result), json.dumps(replay),
             sess.created_at, time.time()))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_match(match_id: int) -> dict | None:
    conn = _db()
    try:
        row = conn.execute("SELECT * FROM matches WHERE id=?", (match_id,)).fetchone()
    finally:
        conn.close()
    return _row(row) if row else None


def get_match_replay(match_id: int) -> dict | None:
    """Normalize one finished match into the public replay contract.

    The viewer initializes ``seed`` through the Environment API and applies
    ``moves`` in order. Legacy rows stored as a plain move list remain readable
    with ``seed=None``.
    """
    m = get_match(match_id)
    if m is None or m["status"] != "finished":
        return None
    raw = m.get("replay") or []
    game_version, seed, options, moves = None, None, None, raw
    if isinstance(raw, dict):
        game_version = raw.get("game_version")
        seed = raw.get("seed")
        options = raw.get("options")
        moves = raw.get("moves") or []
    result = m.get("result") or {}
    return {"schema_version": 1,
            "match_id": m["id"], "game": m["game"], "kind": m["kind"],
            "game_version": game_version,
            "players": m["players"],
            "models": m["models"],
            "result": result,
            "mode": result.get("mode") if isinstance(result, dict) else None,
            "seed": seed, "options": options, "moves": moves,
            "created_at": m["created_at"],
            "finished_at": m["finished_at"]}





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
    """Matches where the user played or owns a participating model."""
    conn = _db()
    try:
        rows = conn.execute(
            "SELECT * FROM matches WHERE status != 'queued' ORDER BY id DESC "
            "LIMIT 200").fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        m = _row(r)
        mine = any(p.get("user_id") == user_id for p in m["players"]) \
            or user_id in [mod.get("owner_id") for mod in (m.get("model_meta") or [])]
        if mine:
            out.append(m)
    return out


# ------------------------------------------------------- model vs model worker

def create_model_match(game: str, principal: dict, model_a: int, model_b) -> int:
    """model_b: model id (int) or "ai:<strategy>". Returns match id.

    13 G3：能力声明制——游戏需声明模型契约；ai: 对手需声明 opponents；
    模型 vs 模型需声明 pvp_options（双人模式开局）。"""
    if not inference.supports_models(game):
        raise ValueError(f"游戏 {game!r} 未声明模型契约，不支持模型对战")
    adapter = GAMES[game]
    ma = model_store.get_model(int(model_a))
    if ma is None or ma["status"] != "active" or ma["owner_id"] != principal["id"]:
        raise ValueError("model_a 不存在或不是你的模型")
    model_meta = [{"type": "model", "side": "p0",
                   "model_id": ma["id"], "name": ma["name"],
                   "owner_id": ma["owner_id"]}]
    opponent_desc = None
    if isinstance(model_b, str) and model_b.startswith("ai:"):
        strategy = model_b[3:]
        opponents = getattr(adapter, "opponents", None) or []
        if strategy not in opponents:
            raise ValueError(f"unknown strategy {strategy!r} "
                             f"(choose from {opponents})")
        opponent_desc = {"type": "ai", "strategy": strategy}
        model_meta.append({"type": "ai", "side": "p1",
                           "strategy": strategy})
    else:
        if not getattr(adapter, "pvp_options", None):
            raise ValueError(f"游戏 {game!r} 不支持模型 vs 模型（未声明双人模式）")
        mb = model_store.get_model(int(model_b))
        if mb is None or mb["status"] != "active":
            raise ValueError("model_b 不存在")
        opponent_desc = {"type": "model", "model_id": mb["id"]}
        model_meta.append({"type": "model", "side": "p1",
                           "model_id": mb["id"], "name": mb["name"],
                           "owner_id": mb["owner_id"]})

    conn = _db()
    try:
        cur = conn.execute(
            "INSERT INTO matches (game, kind, players, models, status, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (game, "model_vs_model",
             json.dumps([{"user_id": principal["id"],
                          "name": principal["nickname"] or principal["username"],
                          "side": "owner"}]),
             json.dumps(model_meta), "queued", time.time()))
        conn.commit()
        match_id = cur.lastrowid
    finally:
        conn.close()

    t = threading.Thread(target=_run_model_match, args=(match_id, game, ma,
                                                        opponent_desc, adapter.meta.get("version")),
                         daemon=True)
    t.start()
    return match_id


def _run_model_match(match_id: int, game: str, model_a: dict, opponent: dict,
                     game_version: str | None = None) -> None:
    with MATCH_WORKER_LIMIT:
        conn = _db()
        try:
            conn.execute("UPDATE matches SET status='running' WHERE id=?",
                         (match_id,))
            conn.commit()
        finally:
            conn.close()
        try:
            adapter = resolve(game, game_version)
            seed = int(time.time_ns() % (1 << 30))
            options = getattr(adapter, "pvp_options", None)
            meta = getattr(adapter, "meta", None) or {}
            game_version = meta.get("version")
            state = adapter.new_state(seed, options)
            sess_a = model_store.load_session(model_a)
            sess_b = None
            if opponent["type"] == "model":
                model_b = model_store.get_model(int(opponent["model_id"]))
                sess_b = model_store.load_session(model_b)
            moves = []
            for _ in range(MATCH_STEP_CAP):
                if state.get("done"):
                    break
                a = inference.model_action(game, sess_a, state, owner=0, adapter=adapter)
                if opponent["type"] == "model":
                    b = inference.model_action(game, sess_b, state, owner=1, adapter=adapter)
                else:
                    b = adapter.opponent_action(
                        state, {"type": "ai", "strategy": opponent["strategy"]})
                moves.append({"tick": state.get("tick", 0), "action": {"p0": a, "p1": b}})
                state = adapter.step_state(state, {"p0": a, "p1": b})
            result = {"winner": state.get("winner"), "cause": state.get("cause"),
                      "damage": state.get("damage", [0, 0]),
                      "tick": state.get("tick", 0)}
            status = "finished"
        except Exception as e:  # model failure -> record and mark failed
            result = {"error": str(e)}
            status = "failed"
        conn = _db()
        try:
            replay = {"schema_version": 1, "game_version": game_version,
                      "seed": seed, "options": options, "moves": moves} \
                if "moves" in dir() and "seed" in dir() else []
            conn.execute(
                "UPDATE matches SET status=?, result=?, replay=?, finished_at=? "
                "WHERE id=?", (status, json.dumps(result),
                               json.dumps(replay),
                               time.time(), match_id))
            conn.commit()
        finally:
            conn.close()
