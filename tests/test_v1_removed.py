"""M4 destructive cleanup: the v1 play/rooms/matchmaking API is really gone.

Design 17 §9 / D36: no compatibility layer, no aliases — old SDKs and bots get
404. These assertions only pin the removals; the v2 behaviour is covered by
test_match_v2.py / test_match_stream.py.
"""
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402

client = TestClient(main.app)

REMOVED = [
    ("POST", "/api/v1/snake/play/sessions"),
    ("GET", "/api/v1/snake/play/sessions/xyz"),
    ("POST", "/api/v1/snake/play/sessions/xyz/actions"),
    ("POST", "/api/v1/snake/play/sessions/xyz/leave"),
    ("GET", "/api/v1/snake/play/sessions/xyz/replay"),
    ("GET", "/api/v1/snake/play/rooms"),
    ("POST", "/api/v1/snake/play/rooms"),
    ("GET", "/api/v1/play/active"),
    ("POST", "/api/v1/microrts/matchmaking/queue"),
    ("DELETE", "/api/v1/microrts/matchmaking/queue"),
    ("GET", "/api/v1/microrts/matchmaking/status"),
    ("GET", "/api/v1/microrts/play/sessions/xyz/chat"),
    ("POST", "/api/v1/microrts/play/sessions/xyz/chat"),
    ("POST", "/api/v1/matches"),                    # 模型对战挑战
    ("GET", "/api/v1/matches/1/replay"),            # 公开回放
    # 设计 17 §8：客户端交分删除，改为结算时服务端自动入榜
    ("POST", "/api/snake/scores"),
]


def test_v1_play_rooms_matchmaking_and_replay_are_removed():
    for method, path in REMOVED:
        response = client.request(method, path, json={})
        assert response.status_code == 404, (method, path, response.status_code,
                                             response.text)
