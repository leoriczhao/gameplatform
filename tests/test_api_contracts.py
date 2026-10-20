"""Machine-readable contracts for Environment, Session, and Match APIs."""
import json
import sys
import time
import uuid
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
import matches as match_store  # noqa: E402
from openenv_helpers import environment_info  # noqa: E402

client = TestClient(main.app)


def _user_headers() -> dict[str, str]:
    username = f"contract_{uuid.uuid4().hex[:10]}"
    r = client.post("/api/v1/auth/register",
                    json={"username": username, "password": "password123"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _response_ref(spec: dict, path: str, method: str) -> str:
    return spec["paths"][path][method]["responses"]["200"]["content"] \
        ["application/json"]["schema"]["$ref"]


def test_openapi_exposes_named_runtime_contracts_and_status_enums():
    spec = client.get("/openapi.json").json()
    assert spec["info"]["version"] == "1.0.0"
    assert not any("/env/" in path for path in spec["paths"])
    assert _response_ref(
        spec, "/api/v1/{game}/play/sessions/{sid}", "get") \
        == "#/components/schemas/GetSessionResponse"
    assert _response_ref(
        spec, "/api/v1/{game}/play/sessions/{sid}/replay", "get") \
        == "#/components/schemas/SessionReplay"
    assert _response_ref(
        spec, "/api/v1/matches/{match_id}/replay", "get") \
        == "#/components/schemas/MatchReplayResponse"

    schemas = spec["components"]["schemas"]
    assert schemas["SessionStatus"]["enum"] == [
        "waiting", "active", "finished", "abandoned", "cancelled"]
    assert schemas["MatchStatus"]["enum"] == [
        "queued", "running", "finished", "failed"]
    assert schemas["MatchKind"]["enum"] == [
        "pve", "pvp", "model_vs_model"]


def test_official_environments_publish_runtime_json_schemas():
    snake = environment_info(client, "snake")
    assert snake["version"]  # package-owned; exact value changes with releases
    assert snake["schemas"]["action"]["enum"] == [0, 1, 2]
    assert "body" in snake["schemas"]["state"]["required"]
    assert snake["schemas"]["observations"]["rotwin"]["x-shape"] == [1334]
    schema_response = client.get("/api/openenv/snake/schema")
    assert schema_response.status_code == 200, schema_response.text
    assert schema_response.json()["action"]["properties"]["value"]["enum"] == [0, 1, 2]

    tetris = environment_info(client, "tetris")
    assert tetris["schemas"]["action"]["enum"] == [0, 1, 2, 3]
    assert tetris["schemas"]["observations"]["grid"]["x-shape"] \
        == [2, 20, 10]

    microrts = environment_info(client, "microrts")
    assert len(microrts["schemas"]["action"]["oneOf"]) == 2
    assert microrts["schemas"]["observations"]["grid"]["x-shape"] \
        == [6, 16, 16]


def test_session_replay_uses_versioned_move_contract():
    headers = _user_headers()
    r = client.post("/api/v1/snake/play/sessions",
                    json={"kind": "pve", "seed": 17}, headers=headers)
    assert r.status_code == 200, r.text
    sid = r.json()["session"]["id"]
    r = client.post(f"/api/v1/snake/play/sessions/{sid}/actions",
                    json={"actions": 1}, headers=headers)
    assert r.status_code == 200, r.text

    replay = client.get(
        f"/api/v1/snake/play/sessions/{sid}/replay").json()
    assert replay["schema_version"] == 1
    assert replay["game_version"] == \
        environment_info(client, "snake")["version"]
    assert replay["options"] is None
    assert replay["result"]["status"] == "active"
    assert replay["moves"] == [{"tick": 0, "action": 1, "opponent": None}]
    client.post(f"/api/v1/snake/play/sessions/{sid}/leave", headers=headers)


def test_public_replay_covers_finished_model_matches():
    now = time.time()
    players = [{"user_id": 7, "name": "owner", "side": "owner"}]
    models = [
        {"type": "model", "side": "p0", "model_id": 11,
         "name": "alpha", "owner_id": 7},
        {"type": "ai", "side": "p1", "strategy": "worker_rush"},
    ]
    stored = {"game_version": "1.0.1", "seed": 99,
              "options": {"opponent": "external"},
              "moves": [{"tick": 0, "action": {"p0": [], "p1": []}}]}
    conn = match_store._db()
    try:
        cur = conn.execute(
            "INSERT INTO matches (game, kind, players, models, status, result, "
            "replay, created_at, finished_at) VALUES (?,?,?,?,?,?,?,?,?)",
            ("microrts", "model_vs_model", json.dumps(players),
             json.dumps(models), "finished",
             json.dumps({"winner": 0, "cause": "eliminated", "tick": 1}),
             json.dumps(stored), now, now))
        conn.commit()
        match_id = cur.lastrowid
    finally:
        conn.close()

    r = client.get(f"/api/v1/matches/{match_id}/replay")
    assert r.status_code == 200, r.text
    replay = r.json()["replay"]
    assert replay["schema_version"] == 1
    assert replay["kind"] == "model_vs_model"
    assert [item["side"] for item in replay["models"]] == ["p0", "p1"]
    assert replay["game_version"] == "1.0.1"
    assert replay["options"] == {"opponent": "external"}
    assert replay["seed"] == 99 and len(replay["moves"]) == 1
