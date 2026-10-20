"""Small helpers for the official OpenEnv WebSocket message protocol.

Keep one websocket open for an episode. Results retain the official
observation/reward/done envelope; these helpers do not emulate batch HTTP.
"""


def ws_message(ws, kind, data=None):
    message = {"type": kind}
    if data is not None:
        message["data"] = data
    ws.send_json(message)
    return ws.receive_json()


def ws_reset(ws, seed=0, **options):
    response = ws_message(ws, "reset", {"seed": seed, **options})
    assert response["type"] == "observation", response
    return response["data"]


def ws_step(ws, action):
    response = ws_message(ws, "step", {"value": action})
    assert response["type"] == "observation", response
    return response["data"]


def ws_state(ws):
    response = ws_message(ws, "state")
    assert response["type"] == "state", response
    return response["data"]


def environment_info(client, game):
    with client.websocket_connect(f"/api/openenv/{game}/ws") as ws:
        return ws_state(ws)["environment"]
