"""Game registry — every registered game is automatically exposed by the
platform (env API, leaderboard, frontend page, docs).

13 G3：平台不再区分「内置/UGC」——注册表里只有「游戏」（均为游戏包经
ProxyAdapter 注册）；可注销，发布/下架/版本切换随之进出注册表。"""
from __future__ import annotations

GAMES: dict = {}


class VersionUnavailable(RuntimeError):
    pass


def resolve(game_id: str, version: str | None = None):
    """Resolve an exact approved version; never silently substitute latest."""
    current = GAMES.get(game_id)
    if current is None:
        raise VersionUnavailable(f"game {game_id!r} is unavailable")
    if version is None or (getattr(current, "meta", {}) or {}).get("version") == version:
        return current
    import ugc
    return ugc.version_adapter(game_id, version)


def register(adapter, source: str = "builtin"):
    if adapter.game_id in GAMES:
        raise ValueError(f"game '{adapter.game_id}' is already registered")
    GAMES[adapter.game_id] = adapter
    return adapter


def unregister(game_id: str) -> None:
    """Remove a game (idempotent). Used by unpublish/version swaps."""
    GAMES.pop(game_id, None)


def sorted_games() -> list:
    return [GAMES[k] for k in sorted(GAMES)]
