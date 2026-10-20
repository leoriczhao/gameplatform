"""Model registry — storage, validation, evaluation.

Design: docs/design/04-模型托管与对抗.md

- ONNX files stored under /data/models/{id}.onnx
- quota: 5 active models per user per game, 20 MB per file
- eval: plays N games server-side and records metrics in meta
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path

import inference

# resolved lazily so tests can set MODELS_DIR after import
def _models_dir() -> Path:
    return Path(os.environ.get("MODELS_DIR", str(SCORES_DB.parent / "models")))


SCORES_DB = Path(os.environ.get("SCORES_DB", "/data/scores.db"))

MAX_MODEL_BYTES = 20 * 1024 * 1024
MAX_MODELS_PER_GAME = 5


def _db() -> sqlite3.Connection:
    SCORES_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(SCORES_DB, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS models (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               owner_id INTEGER NOT NULL,
               game TEXT NOT NULL,
               name TEXT NOT NULL,
               model_type TEXT NOT NULL DEFAULT 'onnx',
               io_contract TEXT NOT NULL,
               file_path TEXT,
               meta TEXT NOT NULL DEFAULT '{}',
               status TEXT NOT NULL DEFAULT 'active',
               created_at REAL NOT NULL
           )"""
    )
    return conn


def _row(row) -> dict:
    return {"id": row[0], "owner_id": row[1], "game": row[2], "name": row[3],
            "model_type": row[4], "io_contract": row[5], "file_path": row[6],
            "meta": json.loads(row[7] or "{}"), "status": row[8],
            "created_at": row[9]}


def create_model(owner_id: int, game: str, name: str, data: bytes,
                 filename: str) -> dict:
    """Validate + store an uploaded ONNX model; raises ValueError."""
    if not inference.supports_models(game):
        raise ValueError(f"game {game!r} 暂不支持模型托管")
    if len(data) > MAX_MODEL_BYTES:
        raise ValueError(f"模型文件超过 20MB 限制")
    if not filename.lower().endswith(".onnx"):
        raise ValueError("仅支持 .onnx 文件")
    if not name or len(name) > 40:
        raise ValueError("模型名 1-40 字符")

    models_dir = _models_dir()
    models_dir.mkdir(parents=True, exist_ok=True)
    tmp = models_dir / f"upload-{time.time_ns()}.onnx"
    tmp.write_bytes(data)
    try:
        contract = inference.check_contract(str(tmp), game)
    except inference.ModelError as e:
        tmp.unlink(missing_ok=True)
        raise ValueError(str(e))

    conn = _db()
    try:
        active = conn.execute(
            "SELECT COUNT(*) FROM models WHERE owner_id=? AND game=? "
            "AND status='active'", (owner_id, game)).fetchone()[0]
        if active >= MAX_MODELS_PER_GAME:
            raise ValueError(f"该游戏最多保留 {MAX_MODELS_PER_GAME} 个活跃模型")
        cur = conn.execute(
            "INSERT INTO models (owner_id, game, name, model_type, io_contract, "
            "file_path, meta, status, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (owner_id, game, name[:40], "onnx", contract, "",
             "{}", "active", time.time()))
        conn.commit()
        model_id = cur.lastrowid
    finally:
        conn.close()

    final_path = _models_dir() / f"{model_id}.onnx"
    tmp.rename(final_path)
    conn = _db()
    try:
        conn.execute("UPDATE models SET file_path=? WHERE id=?",
                     (str(final_path), model_id))
        conn.commit()
    finally:
        conn.close()
    return get_model(model_id)


def get_model(model_id: int) -> dict | None:
    conn = _db()
    try:
        row = conn.execute("SELECT * FROM models WHERE id=?", (model_id,)).fetchone()
    finally:
        conn.close()
    return _row(row) if row else None


def list_models(owner_id: int) -> list[dict]:
    conn = _db()
    try:
        rows = conn.execute(
            "SELECT * FROM models WHERE owner_id=? AND status='active' "
            "ORDER BY id DESC", (owner_id,)).fetchall()
    finally:
        conn.close()
    return [_row(r) for r in rows]


def delete_model(model_id: int, owner_id: int) -> bool:
    conn = _db()
    try:
        cur = conn.execute(
            "UPDATE models SET status='deleted' WHERE id=? AND owner_id=? "
            "AND status='active'", (model_id, owner_id))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def load_session(model: dict):
    return inference.load_model(model["file_path"])


# ------------------------------------------------------------------ eval

def evaluate(model: dict, games: int = 3) -> dict:
    """Play N games server-side with the model; return metrics dict.

    13 G3：唯一的通用路径——声明 opponents 的游戏 = 模型 vs 默认对手
    （双人模式开局），否则单人打分。评估在沙箱内跑（ProxyAdapter）。"""
    game = model["game"]
    sess = load_session(model)
    from registry import GAMES
    adapter = GAMES[game]
    opponents = getattr(adapter, "opponents", None) or []
    scores, lengths, wins = [], [], 0

    for i in range(games):
        seed = int(time.time_ns() % (1 << 30)) + i
        if opponents:
            default = getattr(adapter, "default_opponent", None) or opponents[0]
            state = adapter.new_state(seed, getattr(adapter, "pvp_options", None))
            for step in range(1500):
                if state.get("done"):
                    break
                mine = inference.model_action(game, sess, state, owner=0, adapter=adapter)
                theirs = adapter.opponent_action(
                    state, {"type": "ai", "strategy": default})
                state = adapter.step_state(state, {"p0": mine, "p1": theirs})
            wins += 1 if state.get("winner") == 0 else 0
            scores.append(float(state.get("score", state.get("reward", 0.0))))
            lengths.append(state.get("tick", 0))
        else:
            state = adapter.new_state(seed)
            for step in range(2000):
                if state.get("done"):
                    break
                action = inference.model_action(game, sess, state, adapter=adapter)
                state = adapter.step_state(state, action)
            scores.append(float(state.get("score", state.get("reward", 0.0))))
            lengths.append(state.get("tick", 0))

    metrics = {
        "games": games,
        "avg_score": round(sum(scores) / len(scores), 2),
        "avg_length": round(sum(lengths) / len(lengths), 1),
        "scores": scores,
    }
    if opponents:
        metrics["win_rate"] = round(wins / games, 2)
    return metrics
