"""Legacy v1 record migration (design 17 M4): uid backfill, sealed frames from
versioned replay, privacy-safe defaults, stale rows, idempotency, dry-run."""
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

import main  # noqa: E402,F401  (registers the official packaged games)
import registry  # noqa: E402
import migrate_legacy_matches as migration  # noqa: E402


def _make_db(tmpdir):
    path = Path(tmpdir) / "scores.db"
    conn = sqlite3.connect(path)
    conn.execute(migration.MATCHES_DDL)
    conn.commit()
    return path, conn


def _insert(conn, *, game, kind, players, status="finished", models=(),
            result=None, replay=None):
    cur = conn.execute(
        "INSERT INTO matches (game, kind, players, models, status, result, replay, "
        "created_at, finished_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (game, kind, json.dumps(players), json.dumps(list(models)), status,
         json.dumps(result) if result is not None else None,
         json.dumps(replay) if replay is not None else None, 1.0, 2.0))
    conn.commit()
    return cur.lastrowid


def _snake_pve():
    adapter = registry.GAMES["snake"]
    state = adapter.new_state(3)
    moves = []
    for _ in range(2):
        action = [1, 0]
        moves.append({"tick": int(state.get("tick", 0)), "action": action,
                      "opponent": None})
        state = adapter.step_state(state, action)
    return adapter, {"schema_version": 1, "game_version": adapter.meta["version"],
                     "seed": 3, "options": None, "moves": moves}


def _microrts_pvp():
    adapter = registry.GAMES["microrts"]
    state = adapter.new_state(5, adapter.pvp_options)
    moves = []
    for _ in range(2):
        combined = {"p0": [], "p1": []}
        moves.append({"tick": int(state.get("tick", 0)), "action": combined})
        state = adapter.step_state(state, combined)
    return adapter, {"schema_version": 1, "game_version": adapter.meta["version"],
                     "seed": 5, "options": adapter.pvp_options, "moves": moves}


def _read_frames(path):
    import gzip
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def test_migrate_legacy_matches_frames_uid_seats_and_idempotence():
    snake, snake_replay = _snake_pve()
    microrts, pvp_replay = _microrts_pvp()
    with tempfile.TemporaryDirectory() as tmp:
        path, conn = _make_db(tmp)
        pve_id = _insert(conn, game="snake", kind="pve",
                         players=[{"user_id": 1, "name": "a", "side": "p0"}],
                         result={"winner": 0, "cause": "done", "controller": False},
                         replay=snake_replay)
        pvp_id = _insert(conn, game="microrts", kind="pvp",
                         players=[{"user_id": 1, "name": "a", "side": "p0"},
                                  {"user_id": 2, "name": "b", "side": "p1"}],
                         result={"winner": 1, "cause": "done", "mode": "ranked"},
                         replay=pvp_replay)
        # two-seat PvE: v1 replay embedded the server opponent but recorded p0 only
        pve2_id = _insert(conn, game="microrts", kind="pve",
                          players=[{"user_id": 3, "name": "c", "side": "p0"}],
                          result={"winner": 0, "cause": "done"},
                          replay={"schema_version": 1,
                                  "game_version": microrts.meta["version"],
                                  "seed": 7, "options": None,
                                  "moves": [{"tick": 0, "action": [], "opponent": []}]})
        # unknown historical game version: keep the result, no frames
        bad_id = _insert(conn, game="tetris", kind="pve",
                         players=[{"user_id": 4, "name": "d", "side": "p0"}],
                         result={"winner": 0, "cause": "done"},
                         replay={"schema_version": 1, "game_version": "0.0.0-nope",
                                 "seed": 1, "options": None,
                                 "moves": [{"tick": 0, "action": 0}]})
        # very old plain move list: no seed, not replayable
        plain_id = _insert(conn, game="snake", kind="pve",
                           players=[{"user_id": 5, "name": "e", "side": "p0"}],
                           result={"winner": 0, "cause": "done"},
                           replay=[{"tick": 0, "action": [1, 0]}])
        # a process that died mid model match: saved as aborted
        stale_id = _insert(conn, game="microrts", kind="model_vs_model",
                           players=[{"user_id": 9, "name": "owner", "side": "owner"}],
                           models=[{"type": "model", "side": "p0", "model_id": 1},
                                   {"type": "model", "side": "p1", "model_id": 2}],
                           status="running", result=None, replay=None)

        # dry-run must not touch the schema or write replay files
        dry = migration.migrate(str(path), dry_run=True)
        assert dry["migrated"] == 3 and dry["unavailable"] == 2 and dry["aborted"] == 1
        assert not (Path(tmp) / "replays").exists()
        cols = {r[1] for r in conn.execute("PRAGMA table_info(matches)")}
        assert "uid" not in cols

        counts = migration.migrate(str(path))
        assert counts == {"scanned": 6, "migrated": 3, "unavailable": 2,
                          "aborted": 1, "skipped": 0, "errors": 0}

        def row(mid):
            conn.row_factory = sqlite3.Row
            return conn.execute("SELECT * FROM matches WHERE id=?", (mid,)).fetchone()

        pve = row(pve_id)
        assert len(pve["uid"]) == 12 and pve["mode"] == "practice"
        assert pve["visibility"] == "unlisted" and pve["version"] == snake.meta["version"]
        assert pve["result"] and json.loads(pve["result"])["winner"] == "p0"
        frames = _read_frames(pve["frames"])
        assert [f["tick"] for f in frames] == [0, 0, 1]
        assert frames[0]["actions"] is None and frames[1]["actions"] == {"p0": [1, 0]}
        assert frames[1]["frame"]["tick"] == 1
        seats = {r["seat"]: r for r in conn.execute(
            "SELECT * FROM match_seats WHERE match_id=?", (pve_id,))}
        assert seats["p0"]["user_id"] == 1
        assert json.loads(seats["p0"]["controller"]) == {"type": "human"}

        pvp = row(pvp_id)
        assert json.loads(pvp["result"])["winner"] == "p1"
        assert pvp["mode"] == "ranked"
        pvp_frames = _read_frames(pvp["frames"])
        assert pvp_frames[1]["actions"] == {"p0": [], "p1": []}

        pve2 = row(pve2_id)
        assert _read_frames(pve2["frames"])[1]["actions"] == {"p0": [], "p1": []}
        seats2 = {r["seat"] for r in conn.execute(
            "SELECT seat FROM match_seats WHERE match_id=?", (pve2_id,))}
        assert seats2 == {"p0", "p1"}   # restored AI seat for the two-seat game

        bad = row(bad_id)
        assert bad["uid"] and bad["frames"] is None
        assert json.loads(bad["result"])["winner"] == "p0"
        assert row(plain_id)["uid"] and row(plain_id)["frames"] is None

        stale = row(stale_id)
        assert stale["status"] == "aborted" and stale["uid"]
        assert json.loads(stale["result"])["cause"] == "server_restart"
        stale_seats = {r["seat"]: json.loads(r["controller"]) for r in conn.execute(
            "SELECT seat, controller FROM match_seats WHERE match_id=?", (stale_id,))}
        assert stale_seats["p0"]["type"] == "model"

        again = migration.migrate(str(path))
        assert again["skipped"] == 6 and again["migrated"] == 0
        conn.close()


def test_migrate_limit_stops_early():
    with tempfile.TemporaryDirectory() as tmp:
        path, conn = _make_db(tmp)
        _insert(conn, game="snake", kind="pve",
                players=[{"user_id": 1, "name": "a", "side": "p0"}],
                result={"winner": 0, "cause": "done"},
                replay={"schema_version": 1, "game_version": "1.0.0", "seed": 3,
                        "options": None, "moves": []})
        _insert(conn, game="snake", kind="pve",
                players=[{"user_id": 2, "name": "b", "side": "p0"}],
                result={"winner": 0, "cause": "done"}, replay=[{"tick": 0}])
        counts = migration.migrate(str(path), limit=1)
        assert counts["migrated"] + counts["unavailable"] == 1
        remaining = conn.execute("SELECT COUNT(*) FROM matches WHERE uid IS NULL").fetchone()[0]
        assert remaining == 1
        conn.close()
