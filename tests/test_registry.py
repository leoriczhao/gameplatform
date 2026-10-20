"""Registry contract tests (13 G3): games come from the seeded official
packages — the registry holds only ProxyAdapters loaded via the startup
path (bootstrap admin -> seed packaged-games/* -> load published)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import main  # noqa: E402,F401  — 导入触发 bootstrap + 播种 + 注册表加载
from registry import GAMES  # noqa: E402


def test_all_games_registered():
    assert set(GAMES) == {"snake", "tetris", "microrts"}


def test_adapters_conform_to_interface():
    for game_id, adapter in GAMES.items():
        assert adapter.game_id == game_id
        assert adapter.name and adapter.description
        info = adapter.info()
        assert "actions" in info, game_id
        assert "default_rewards" in info, game_id
        assert "obs_modes" in info, game_id
        assert "max_batch" in info, game_id
        assert len(adapter.score_bounds) == 2
        assert adapter.score_bounds[0] <= adapter.score_bounds[1]


def test_new_state_same_seed_reproducible():
    for adapter in GAMES.values():
        a = adapter.new_state(42)
        b = adapter.new_state(42)
        assert a == b, adapter.game_id
        assert a["seed"] == 42
        adapter.validate_state(a)  # must not raise


def test_validate_action():
    snake = GAMES["snake"]
    for a in (0, 1, 2):
        snake.validate_action(a)
    for bad in (3, -1, 7):
        try:
            snake.validate_action(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"snake accepted action {bad}")

    tetris = GAMES["tetris"]
    for a in (0, 1, 2, 3):
        tetris.validate_action(a)
    for bad in (4, -1):
        try:
            tetris.validate_action(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"tetris accepted action {bad}")


def test_info_contract_fields():
    snake_info = GAMES["snake"].info()
    assert snake_info["grid"] == [20, 20]
    assert snake_info["actions"] == {"0": "left", "1": "straight", "2": "right"}
    assert snake_info["obs_shape"] == [3, 22, 22]

    tetris_info = GAMES["tetris"].info()
    assert tetris_info["grid"] == [10, 20]
    assert tetris_info["actions"] == {"0": "left", "1": "right",
                                      "2": "rotate", "3": "hard_drop"}
    assert tetris_info["obs_shape"] == [2, 20, 10]


def test_catalog_has_no_source_field():
    """13 G3：目录不再区分内置/UGC。"""
    import os
    if os.environ.get("SCORES_DB"):
        pass  # main 已导入；直接测 API
    from fastapi.testclient import TestClient
    client = TestClient(main.app)
    r = client.get("/api/games")
    assert r.status_code == 200
    for g in r.json()["games"]:
        assert "source" not in g
        assert g.get("author") == "官方", g   # 种子包属管理员 → 官方
