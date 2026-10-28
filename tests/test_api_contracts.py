"""Machine-readable contracts for Environment and match history APIs.

The v2 Match protocol is the only match protocol after M4 (design 17 §9): the
v1 play/session/room/matchmaking contracts and the model-challenge/replay
endpoints are gone with no compatibility layer, while the OpenAPI version and
the environment schemas stay stable.
"""
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from openenv_helpers import environment_info  # noqa: E402

client = TestClient(main.app)


def _response_ref(spec: dict, path: str, method: str) -> str:
    return spec["paths"][path][method]["responses"]["200"]["content"] \
        ["application/json"]["schema"]["$ref"]


def test_openapi_exposes_v2_matches_and_history_contracts():
    spec = client.get("/openapi.json").json()
    assert spec["info"]["version"] == "1.0.0"
    assert not any("/env/" in path for path in spec["paths"])

    # retained history projection (v2 records + archived v1 rows)
    assert _response_ref(spec, "/api/v1/matches", "get") \
        == "#/components/schemas/MatchesResponse"
    assert _response_ref(spec, "/api/v1/matches/{match_id}", "get") \
        == "#/components/schemas/MatchDetailResponse"

    # the v2 Match surface (design 17 §5) is the only match protocol
    for path, method in (
        ("/api/v2/matches", "post"),
        ("/api/v2/matches/{uid}", "get"),
        ("/api/v2/matches/{uid}/actions", "post"),
        ("/api/v2/matches/{uid}/frames", "get"),
        ("/api/v2/matches/{uid}/stream", "get"),
        ("/api/v2/me/matches", "get"),
        ("/api/v2/{game}/matchmaking/queue", "post"),
        ("/api/v2/{game}/matchmaking/status", "get"),
    ):
        assert path in spec["paths"] and method in spec["paths"][path], (path, method)


def test_removed_v1_contracts_are_absent():
    spec = client.get("/openapi.json").json()
    paths = spec["paths"]
    # v1 play/rooms/matchmaking are deleted, not aliased (design 17 §9)
    assert not any("/play/" in path for path in paths)
    assert not any(path.startswith("/api/v1/") and "matchmaking" in path
                   for path in paths)
    assert "/api/v1/matches/{match_id}/replay" not in paths
    assert "post" not in {m.lower() for m in paths["/api/v1/matches"]}
    assert "get" in {m.lower() for m in paths["/api/v1/matches"]}

    schemas = spec["components"]["schemas"]
    for gone in ("SessionStatus", "SessionView", "SessionReplay", "RoomView",
                 "CreateMatchResponse", "MatchReplay", "MatchReplayResponse"):
        assert gone not in schemas, gone
    assert schemas["MatchStatus"]["enum"] == [
        "queued", "running", "finished", "failed",
        "waiting", "active", "aborted", "cancelled"]   # v2 对局状态（设计 17）
    assert schemas["MatchKind"]["enum"] == ["pve", "pvp", "model_vs_model"]
    assert "MatchRecord" in schemas and "MatchDetailResponse" in schemas


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
