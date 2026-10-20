"""Seed loader (13 G3): main._seed_bundled_games() is the cold-start path —
packaged-games/* go through the exact upload pipeline and publish as 官方.

In the shared pytest process the loader already ran at main import (conftest
pre-seeds an admin), so this test re-runs it to check idempotency and that
the full platform surface is live for the seeded games."""
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
import registry  # noqa: E402
import ugc  # noqa: E402
from openenv_helpers import environment_info  # noqa: E402

client = TestClient(main.app)


def test_cold_start_seed_idempotent():
    v_before = {}
    for slug in ("snake", "tetris", "microrts"):
        g = ugc.get_game_by_slug(slug)
        assert g is not None and g["status"] == "published", slug
        v_before[slug] = ugc.latest_version(g["id"])["id"]

    main._seed_bundled_games()   # 幂等：同版本跳过，不重复入库

    for slug, vid in v_before.items():
        g = ugc.get_game_by_slug(slug)
        assert ugc.latest_version(g["id"])["id"] == vid, f"{slug} 被重复播种"


def test_seeded_games_live_in_registry_and_env():
    main._seed_bundled_games()
    ugc.load_published_into_registry()
    for slug in ("snake", "tetris", "microrts"):
        assert slug in registry.GAMES, slug
        info = environment_info(client, slug)
        assert info["game"] == slug and info["version"]
        assert info["max_concurrent_envs"] == 64
    # 目录：官方包作者显示「官方」，无 source 字段（13 G3）
    catalog = client.get("/api/games").json()["games"]
    for g in catalog:
        assert "source" not in g
        if g["id"] in ("snake", "tetris", "microrts"):
            assert g["author"] == "官方", g["id"]
