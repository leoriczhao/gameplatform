"""UGC store (11 P3): tables, quotas, upload flow, lifecycle state machine,
registry sync, smoke tests, notifications.

Design: docs/design/10 §6-§8。状态机：
  draft ──submit──▶ pending ──approve──▶ published
    ▲                 │ reject            │ unpublish(作者)/ban(管理员)
    └─────────────────┘                  ▼ draft/banned
  published ──熔断──▶ paused ──resume──▶ published
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from pathlib import Path

import contract_check
import registry
import ugc_pack
import ugc_proxy
import ugc_runner
import ugc_static

SCORES_DB = Path(os.environ.get("SCORES_DB", "/data/scores.db"))
MODELS_DIR = Path(os.environ.get("MODELS_DIR", str(SCORES_DB.parent / "models")))
MAX_DRAFTS = 5        # 作者名下 draft/pending/published 游戏总数
MAX_PUBLISHED = 3     # 其中 published 上限
SMOKE_STEPS = 20


def _db() -> sqlite3.Connection:
    SCORES_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(SCORES_DB, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS ugc_games (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               owner_id INTEGER NOT NULL,
               slug TEXT NOT NULL UNIQUE,
               title TEXT NOT NULL,
               description TEXT,
               status TEXT NOT NULL DEFAULT 'draft',
               pause_reason TEXT,
               created_at REAL NOT NULL, updated_at REAL NOT NULL)""")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS ugc_versions (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               game_id INTEGER NOT NULL,
               version TEXT NOT NULL,
               changelog TEXT,
               package_path TEXT NOT NULL,
               meta TEXT NOT NULL,
               status TEXT NOT NULL DEFAULT 'draft',
               review_note TEXT,
               reviewer_id INTEGER,
               created_at REAL NOT NULL)""")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_ugcv_game ON ugc_versions(game_id, id)")
    return conn


def ensure_schema() -> None:
    _db().close()
    import auth as auth_store
    import social as social_store
    auth_store._db().close()   # users 表（通知/作者名查询依赖）
    social_store._db().close()  # notifications 表


def _row_game(r) -> dict:
    return {"id": r[0], "owner_id": r[1], "slug": r[2], "title": r[3],
            "description": r[4], "status": r[5], "pause_reason": r[6],
            "created_at": r[7], "updated_at": r[8]}


def _row_version(r) -> dict:
    meta = json.loads(r[5] or "{}")
    return {"id": r[0], "game_id": r[1], "version": r[2],
            "changelog": r[3], "package_path": r[4], "meta": meta,
            "status": r[6], "review_note": r[7], "reviewer_id": r[8],
            "created_at": r[9]}
# ------------------------------------------------------------ queries/helpers

def get_game(game_id: int) -> dict | None:
    conn = _db()
    try:
        r = conn.execute("SELECT * FROM ugc_games WHERE id = ?",
                         (game_id,)).fetchone()
    finally:
        conn.close()
    return _row_game(r) if r else None


def get_game_by_slug(slug: str) -> dict | None:
    conn = _db()
    try:
        r = conn.execute("SELECT * FROM ugc_games WHERE slug = ?",
                         (slug,)).fetchone()
    finally:
        conn.close()
    return _row_game(r) if r else None


def latest_version(game_id: int, statuses=None) -> dict | None:
    conn = _db()
    try:
        if statuses:
            marks = ",".join("?" * len(statuses))
            r = conn.execute(
                f"SELECT * FROM ugc_versions WHERE game_id = ? AND status IN "
                f"({marks}) ORDER BY id DESC LIMIT 1", (game_id, *statuses)).fetchone()
        else:
            r = conn.execute(
                "SELECT * FROM ugc_versions WHERE game_id = ? "
                "ORDER BY id DESC LIMIT 1", (game_id,)).fetchone()
    finally:
        conn.close()
    return _row_version(r) if r else None


def active_version(game_id: int) -> dict | None:
    return latest_version(game_id, statuses=["active"])


def version_adapter(slug: str, version: str):
    """Archived approved packages remain executable while the game is published."""
    conn = _db()
    try:
        row = conn.execute(
            "SELECT v.* FROM ugc_versions v JOIN ugc_games g ON g.id=v.game_id "
            "WHERE g.slug=? AND g.status='published' AND v.version=? "
            "AND v.status IN ('active','superseded') ORDER BY v.id DESC LIMIT 1",
            (slug, version)).fetchone()
    finally:
        conn.close()
    if row is None:
        raise registry.VersionUnavailable(f"game {slug!r} version {version!r} is unavailable")
    v = _row_version(row)
    if not Path(v["package_path"]).is_dir():
        raise registry.VersionUnavailable(f"game {slug!r} version {version!r} package is missing")
    meta = dict(v["meta"].get("meta", v["meta"]))
    meta["renderer_enabled"] = bool(v["meta"].get("renderer_enabled"))
    return ugc_proxy.ProxyAdapter(slug, v["package_path"], meta,
                                  on_unhealthy=lambda _gid: fuse(v["game_id"]))


def _versions_of(game_id: int) -> list[dict]:
    conn = _db()
    try:
        rows = conn.execute(
            "SELECT * FROM ugc_versions WHERE game_id = ? "
            "ORDER BY id DESC", (game_id,)).fetchall()
    finally:
        conn.close()
    return [_row_version(r) for r in rows]


def _set_game_status(game_id: int, status: str,
                     pause_reason: str | None = None) -> None:
    conn = _db()
    try:
        conn.execute(
            "UPDATE ugc_games SET status = ?, pause_reason = ?, updated_at = ? "
            "WHERE id = ?", (status, pause_reason, time.time(), game_id))
        conn.commit()
    finally:
        conn.close()


def _set_version_status(version_id: int, status: str, note: str | None = None,
                        reviewer_id: int | None = None) -> None:
    conn = _db()
    try:
        conn.execute(
            "UPDATE ugc_versions SET status = ?, review_note = ?, "
            "reviewer_id = ? WHERE id = ?",
            (status, note, reviewer_id, version_id))
        conn.commit()
    finally:
        conn.close()


def _notify(user_id: int, kind: str, body: str, link: str | None = None) -> None:
    conn = _db()
    try:
        conn.execute(
            "INSERT INTO notifications (user_id, kind, body, link, read, "
            "created_at) VALUES (?,?,?,?,0,?)",
            (user_id, kind, body, link, time.time()))
        conn.commit()
    finally:
        conn.close()


def _notify_admins(kind: str, body: str, link: str | None = None) -> None:
    conn = _db()
    try:
        rows = conn.execute("SELECT id FROM users WHERE role = 'admin'").fetchall()
    finally:
        conn.close()
    for (aid,) in rows:
        _notify(aid, kind, body, link)


def _quota_ok(owner_id: int) -> tuple[bool, str]:
    conn = _db()
    try:
        total = conn.execute(
            "SELECT COUNT(*) FROM ugc_games WHERE owner_id = ? AND status IN "
            "('draft','pending','published','paused')", (owner_id,)).fetchone()[0]
        published = conn.execute(
            "SELECT COUNT(*) FROM ugc_games WHERE owner_id = ? AND status = "
            "'published'", (owner_id,)).fetchone()[0]
    finally:
        conn.close()
    if total >= MAX_DRAFTS:
        return False, f"草稿/发布中游戏已达上限 {MAX_DRAFTS} 个"
    return True, ""


def _publish_quota_ok(owner_id: int) -> tuple[bool, str]:
    conn = _db()
    try:
        published = conn.execute(
            "SELECT COUNT(*) FROM ugc_games WHERE owner_id = ? AND status = "
            "'published'", (owner_id,)).fetchone()[0]
    finally:
        conn.close()
    if published >= MAX_PUBLISHED:
        return False, f"公开游戏已达上限 {MAX_PUBLISHED} 个"
    return True, ""
# ------------------------------------------------------------ smoke + upload

def _smoke(slug: str, game_dir: Path, meta: dict) -> dict:
    """沙箱冒烟：info/new_state/20 步 sample_action 推进 + PvP 复合步。"""
    wid = f"smoke:{slug}:{time.time_ns()}"
    ugc_runner.drop_worker(wid)
    w = None
    try:
        w = ugc_runner.GameWorker(wid, game_dir)
        info = w.request("info")
        s = w.request("new_state", seed=1)
        w.request("validate_state", state=s)
        steps = 0
        while steps < SMOKE_STEPS and not s.get("done"):
            try:
                a = w.request("sample_action", state=s)
                w.request("validate_action", action=a, state=s)
            except ugc_runner.WorkerError:
                break
            s = w.request("step_state", state=s, action=a)
            w.request("validate_state", state=s)
            steps += 1
        if (meta.get("pvp") or {}).get("enabled"):
            # PvP 开局附加参数（如 microrts {opponent: external}）进入双人模式
            pvp_opts = (meta.get("pvp") or {}).get("options")
            s_pvp = w.request("new_state", seed=1, options=pvp_opts) \
                if pvp_opts else s
            a0 = w.request("sample_action", state=s_pvp)
            s2 = w.request("step_state", state=s_pvp,
                           action={"p0": a0, "p1": a0})
            w.request("validate_state", state=s2)
        bounds = w.request("score_bounds")
        return {"ok": True, "steps": steps, "done": bool(s.get("done")),
                "score_bounds": bounds, "info": info}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    finally:
        if w is not None:
            w.stop()


def _version_tuple(v: str) -> tuple[int, ...]:
    try:
        return tuple(int(x) for x in v.split("."))
    except ValueError:
        return ()


def _cleanup_dir(dest: Path) -> None:
    import shutil
    root = (MODELS_DIR / "ugc").resolve()
    if str(dest.resolve()).startswith(str(root)):
        shutil.rmtree(dest, ignore_errors=True)


def _reject(msg: str):
    raise ValueError(msg)


def _check_resources(dest: Path) -> None:
    """包内 .npz/.npy 资源必须可被 numpy 加载（12 §3 只读资源校验）。"""
    import numpy as np
    for p in sorted(dest.rglob("*.npz")):
        try:
            np.load(str(p), allow_pickle=False)
        except Exception as e:
            _cleanup_dir(dest)
            _reject(f"资源文件损坏：{p.name}（{type(e).__name__}）")
    for p in sorted(dest.rglob("*.npy")):
        try:
            np.load(str(p), allow_pickle=False)
        except Exception as e:
            _cleanup_dir(dest)
            _reject(f"资源文件损坏：{p.name}（{type(e).__name__}）")


def _ingest(data: bytes, expect_slug: str | None = None,
            renderer_enabled: bool = False) -> tuple[dict, Path]:
    """校验 → 静态扫描 → 解包 → 资源校验 → 冒烟。返回 (stored_meta, extracted_dir)。

    renderer_enabled 仅官方种子包置 True；UGC 由管理员审核后显式开启（16 §5.1）。
    """
    builtin = set(registry.GAMES)   # 已注册的 slug 视为占用（种子包先占，天然防冲突）
    if expect_slug is not None:
        builtin.discard(expect_slug)   # 自家已发布游戏的 slug 不算冲突
    report = ugc_pack.validate_package(data, builtin_games=builtin)
    meta = report["meta"]
    if expect_slug is not None and meta["slug"] != expect_slug:
        _reject(f"slug 不可更改（{expect_slug} → {meta['slug']}）")
    dest = MODELS_DIR / "ugc" / meta["slug"] / f"v{int(time.time_ns())}"
    ugc_pack.extract_package(data, dest)
    _check_resources(dest)
    scan = ugc_static.scan_dir(dest)
    if not scan["ok"]:
        _cleanup_dir(dest)
        head = "; ".join(f"{v['file']}:{v['line']} {v['detail']}"
                           for v in scan["violations"][:3])
        _reject(f"静态扫描未通过：{head}")
    rscan = None
    rend = meta.get("renderer")
    if rend:
        try:
            rtext = (dest / rend["entry"]).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            _cleanup_dir(dest)
            _reject("渲染器文件不可读（需 UTF-8 文本）")
        rscan = ugc_static.scan_renderer(rtext)
        if not rscan["ok"]:
            _cleanup_dir(dest)
            head = "; ".join(f"{v['line']} {v['detail']}"
                             for v in rscan["violations"][:3])
            _reject(f"渲染器静态扫描未通过：{head}")
    smoke = _smoke(meta["slug"], dest, meta)
    if not smoke["ok"]:
        _cleanup_dir(dest)
        _reject(f"沙箱冒烟失败：{smoke['error']}")
    stored = {"meta": meta, "sha256": report["sha256"],
              "scan": scan, "renderer_scan": rscan, "smoke": smoke,
              "renderer_enabled": bool(rend) and renderer_enabled}
    return stored, dest


def create_game(owner_id: int, data: bytes, changelog: str) -> tuple[dict, dict]:
    ok, msg = _quota_ok(owner_id)
    if not ok:
        _reject(msg)
    stored, dest = _ingest(data)
    meta = stored["meta"]
    if get_game_by_slug(meta["slug"]) is not None:
        _cleanup_dir(dest)
        _reject(f"slug {meta['slug']!r} 已被占用")
    conn = _db()
    try:
        cur = conn.execute(
            "INSERT INTO ugc_games (owner_id, slug, title, description, status, "
            "created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
            (owner_id, meta["slug"], meta["title"], meta["description"],
             "draft", time.time(), time.time()))
        game_id = cur.lastrowid
        conn.execute(
            "INSERT INTO ugc_versions (game_id, version, changelog, package_path, "
            "meta, status, created_at) VALUES (?,?,?,?,?,?,?)",
            (game_id, meta["version"], changelog or "", str(dest),
             json.dumps(stored), "draft", time.time()))
        conn.commit()
    finally:
        conn.close()
    return get_game(game_id), latest_version(game_id)


def seed_game(owner_id: int, data: bytes,
              changelog: str = "") -> tuple[dict, dict]:
    """官方种子包（12 §4.2 / 13 G1）：与用户上传同一条管线
    （validate→scan→extract→资源校验→smoke），但免人工审核，直接
    published/active。按 slug 幂等：同版本跳过；更高版本自动升级并 swap。"""
    report0 = ugc_pack.validate_package(data, builtin_games=())
    slug0 = report0["meta"]["slug"]
    stored, dest = _ingest(data, expect_slug=slug0, renderer_enabled=True)
    meta = stored["meta"]
    game = get_game_by_slug(meta["slug"])
    conn = _db()
    try:
        if game is None:
            cur = conn.execute(
                "INSERT INTO ugc_games (owner_id, slug, title, description, status, "
                "created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                (owner_id, meta["slug"], meta["title"], meta["description"],
                 "published", time.time(), time.time()))
            game_id = cur.lastrowid
            conn.execute(
                "INSERT INTO ugc_versions (game_id, version, changelog, package_path, "
                "meta, status, created_at) VALUES (?,?,?,?,?,?,?)",
                (game_id, meta["version"], changelog or "", str(dest),
                 json.dumps(stored), "active", time.time()))
        else:
            game_id = game["id"]
            known = [_version_tuple(v["version"]) for v in _versions_of(game_id)]
            max_v = max((t for t in known if t), default=())
            new_v = _version_tuple(meta["version"])
            if not new_v or not max_v or new_v <= max_v:
                _cleanup_dir(dest)
                if new_v and new_v == max_v:
                    conn.commit()
                    return get_game(game_id), latest_version(game_id)
                _reject("种子包版本号必须高于已有版本（x.y.z 递增）")
            old = active_version(game_id)
            if old is not None:
                conn.execute("UPDATE ugc_versions SET status='superseded' "
                             "WHERE id = ?", (old["id"],))
            conn.execute(
                "INSERT INTO ugc_versions (game_id, version, changelog, package_path, "
                "meta, status, created_at) VALUES (?,?,?,?,?,?,?)",
                (game_id, meta["version"], changelog or "", str(dest),
                 json.dumps(stored), "active", time.time()))
            conn.execute(
                "UPDATE ugc_games SET status='published', updated_at=? WHERE id=?",
                (time.time(), game_id))
        conn.commit()
    finally:
        conn.close()
    return get_game(game_id), latest_version(game_id)


def add_version(owner_id: int, game_id: int, data: bytes,
                changelog: str) -> tuple[dict, dict]:
    game = get_game(game_id)
    if game is None or game["owner_id"] != owner_id:
        raise KeyError("游戏不存在")
    if game["status"] == "banned":
        _reject("游戏已下架，无法更新")
    stored, dest = _ingest(data, expect_slug=game["slug"])
    meta = stored["meta"]
    known = [_version_tuple(v["version"]) for v in _versions_of(game_id)]
    max_v = max((t for t in known if t), default=())
    new_v = _version_tuple(meta["version"])
    if not new_v or not max_v or new_v <= max_v:
        _cleanup_dir(dest)
        _reject("新版本号必须高于已有版本（x.y.z 递增）")
    conn = _db()
    try:
        conn.execute(
            "INSERT INTO ugc_versions (game_id, version, changelog, package_path, "
            "meta, status, created_at) VALUES (?,?,?,?,?,?,?)",
            (game_id, meta["version"], changelog or "", str(dest),
             json.dumps(stored), "draft", time.time()))
        conn.execute(
            "UPDATE ugc_games SET updated_at = ? WHERE id = ?",
            (time.time(), game_id))
        conn.commit()
    finally:
        conn.close()
    return get_game(game_id), latest_version(game_id)
# ------------------------------------------------------------ lifecycle

_MOUNTED_SLUGS: set[str] = set()
_ROUTER_MOUNTER = None


def set_router_mounter(fn) -> None:
    """main.py 注入：发布时挂载 OpenEnv 环境与 AI/排行榜等平台路由。"""
    global _ROUTER_MOUNTER
    _ROUTER_MOUNTER = fn


def _register_game(game: dict, version: dict) -> None:
    meta = dict(version["meta"].get("meta", version["meta"]))
    meta["renderer_enabled"] = bool(version["meta"].get("renderer_enabled"))
    author = None
    try:
        import auth as auth_store
        u = auth_store.user_by_id(game["owner_id"])
        if u:
            # 官方种子包（owner 为管理员）在目录显示「官方」（13 G3）
            author = "官方" if u.get("role") in ("admin", "system") \
                else (u.get("nickname") or u.get("username"))
    except Exception:
        pass
    adapter = ugc_proxy.ProxyAdapter(game["slug"], version["package_path"], meta,
                                     author=author,
                                     on_unhealthy=lambda _sid: fuse(game["id"]))
    info = adapter.info()  # require a usable sandbox before exposing the new version
    # A1：game.yaml contract.* 必须与运行时 schemas 一致（否则拒绝注册）
    contract_check.validate_contract(meta, info)
    registry.GAMES[game["slug"]] = adapter
    if game["slug"] not in _MOUNTED_SLUGS and _ROUTER_MOUNTER is not None:
        _ROUTER_MOUNTER(adapter)   # 挂一次即可；env 路由内部按请求动态解析 adapter
        _MOUNTED_SLUGS.add(game["slug"])


def submit(game_id: int, owner_id: int) -> dict:
    game = get_game(game_id)
    if game is None or game["owner_id"] != owner_id:
        raise KeyError("游戏不存在")
    if game["status"] not in ("draft", "published"):
        _reject(f"当前状态 {game['status']} 不能提交审核")
    v = latest_version(game_id)
    if v is None or v["status"] not in ("draft", "active"):
        _reject("没有可提交的版本")
    _set_version_status(v["id"], "pending", note=None, reviewer_id=None)
    if game["status"] == "draft":
        _set_game_status(game_id, "pending")
    _notify_admins("ugc_submit",
                   f"UGC 游戏《{game['title']}》v{v['version']} 提交审核",
                   "/admin")
    return get_game(game_id)


def approve(game_id: int, reviewer_id: int) -> dict:
    game = get_game(game_id)
    if game is None:
        raise KeyError("游戏不存在")
    v = latest_version(game_id, statuses=["pending"])
    if v is None:
        _reject("没有待审核的版本")
    ok, msg = _publish_quota_ok(game["owner_id"])
    if not ok:
        _reject(msg)
    # 先注册（含契约校验）；校验失败不落任何状态变更
    _register_game(game, v)
    old = active_version(game_id)
    if old is not None:
        _set_version_status(old["id"], "superseded")
    _set_version_status(v["id"], "active", reviewer_id=reviewer_id)
    _set_game_status(game_id, "published")
    _notify(game["owner_id"], "ugc_approved",
            f"你的游戏《{game['title']}》v{v['version']} 已通过审核并公开发布",
            f"/games/ugc/{game['slug']}")
    return get_game(game_id)


def reject(game_id: int, reviewer_id: int, note: str) -> dict:
    game = get_game(game_id)
    if game is None:
        raise KeyError("游戏不存在")
    v = latest_version(game_id, statuses=["pending"])
    if v is None:
        _reject("没有待审核的版本")
    _set_version_status(v["id"], "rejected", note=note, reviewer_id=reviewer_id)
    if game["status"] == "pending":
        _set_game_status(game_id, "draft")
    _notify(game["owner_id"], "ugc_rejected",
            f"你的游戏《{game['title']}》v{v['version']} 审核未通过：{note}")
    return get_game(game_id)
def unpublish(game_id: int, owner_id: int) -> dict:
    game = get_game(game_id)
    if game is None or game["owner_id"] != owner_id:
        raise KeyError("游戏不存在")
    if game["status"] != "published":
        _reject("只有已公开的游戏可以下架")
    _set_game_status(game_id, "draft")
    registry.unregister(game["slug"])
    ugc_runner.drop_worker(game["slug"])
    _notify_admins("ugc_unpublished",
                   f"作者下架了《{game['title']}》（@{game['slug']}）", "/admin")
    return get_game(game_id)


def _set_renderer_flag(version_id: int, enabled: bool) -> None:
    """就地改写某版本的 stored JSON 里的 renderer_enabled（16 §5.1）。"""
    conn = _db()
    try:
        r = conn.execute("SELECT meta FROM ugc_versions WHERE id = ?",
                         (version_id,)).fetchone()
        if r is None:
            return
        stored = json.loads(r[0] or "{}")
        stored["renderer_enabled"] = bool(enabled)
        conn.execute("UPDATE ugc_versions SET meta = ? WHERE id = ?",
                     (json.dumps(stored), version_id))
        conn.commit()
    finally:
        conn.close()


def set_renderer_enabled(game_id: int, enabled: bool) -> dict:
    """管理员开关沙箱渲染器（16 §5.1）：作用于最新版本并同步注册表。"""
    v = latest_version(game_id)
    if v is None:
        raise KeyError("游戏不存在")
    if not (v["meta"].get("meta") or {}).get("renderer"):
        _reject("该版本未声明 renderer")
    _set_renderer_flag(v["id"], enabled)
    game = get_game(game_id)
    if game is not None and game["status"] == "published":
        _register_game(game, latest_version(game_id))
    return latest_version(game_id)


def version_row(slug: str, version: str,
                statuses=("active", "superseded")) -> tuple[dict, dict] | None:
    """按 slug + version 取版本行（资源/帧路由用）。"""
    game = get_game_by_slug(slug)
    if game is None:
        return None
    for v in _versions_of(game["id"]):
        if v["version"] == version and v["status"] in statuses:
            return game, v
    return None


def ban(game_id: int, admin_id: int) -> dict:
    game = get_game(game_id)
    if game is None:
        raise KeyError("游戏不存在")
    v = latest_version(game_id)
    if v is not None:
        _set_renderer_flag(v["id"], False)   # 下架即关闭沙箱渲染器
    _set_game_status(game_id, "banned", pause_reason=None)
    registry.unregister(game["slug"])
    ugc_runner.drop_worker(game["slug"])
    _notify(game["owner_id"], "ugc_banned",
            f"你的游戏《{game['title']}》已被管理员下架", "/ugc")
    return get_game(game_id)


def unban(game_id: int, admin_id: int) -> dict:
    game = get_game(game_id)
    if game is None:
        raise KeyError("游戏不存在")
    _set_game_status(game_id, "draft")   # 需作者重新提交审核
    _notify(game["owner_id"], "ugc_unbanned",
            f"你的游戏《{game['title']}》已恢复，可重新提交审核", "/ugc")
    return get_game(game_id)


def pause(game_id: int, reason: str) -> dict:
    game = get_game(game_id)
    if game is None:
        raise KeyError("游戏不存在")
    if game["status"] != "published":
        _reject("只有已公开的游戏可以暂停")
    _set_game_status(game_id, "paused", pause_reason=reason)
    registry.unregister(game["slug"])
    ugc_runner.drop_worker(game["slug"])
    _notify(game["owner_id"], "ugc_paused",
            f"你的游戏《{game['title']}》已被暂停：{reason}", "/ugc")
    return get_game(game_id)


def resume(game_id: int) -> dict:
    game = get_game(game_id)
    if game is None:
        raise KeyError("游戏不存在")
    if game["status"] != "paused":
        _reject("只有暂停中的游戏可以恢复")
    v = active_version(game_id)
    if v is None:
        _reject("没有可恢复的版本")
    _set_game_status(game_id, "published")
    game = get_game(game_id)
    _register_game(game, v)
    _notify(game["owner_id"], "ugc_resumed",
            f"你的游戏《{game['title']}》已恢复运行", "/ugc")
    return game


def fuse(game_id: int) -> None:
    """worker 熔断回调：连续失败 → 暂停游戏 + 通知（设计 10 §5 第 5 层）。"""
    game = get_game(game_id)
    if game is None or game["status"] != "published":
        return
    reason = "熔断：沙箱连续失败（超时/崩溃/超限），请检查后重新提交"
    _set_game_status(game_id, "paused", pause_reason=reason)
    registry.unregister(game["slug"])
    ugc_runner.drop_worker(game["slug"])
    _notify(game["owner_id"], "ugc_paused",
            f"你的游戏《{game['title']}》已触发熔断保护并暂停", "/ugc")
    _notify_admins("ugc_fused", f"UGC《{game['title']}》触发熔断已暂停", "/admin")
def rollback(game_id: int, version_id: int, admin_id: int) -> dict:
    game = get_game(game_id)
    if game is None:
        raise KeyError("游戏不存在")
    v = None
    for item in _versions_of(game_id):
        if item["id"] == version_id:
            v = item
            break
    if v is None or v["status"] != "superseded":
        _reject("只能回滚到已归档的历史版本")
    old = active_version(game_id)
    if old is not None:
        _set_version_status(old["id"], "superseded")
    _set_version_status(v["id"], "active", reviewer_id=admin_id)
    _register_game(game, v)
    _notify(game["owner_id"], "ugc_rollback",
            f"你的游戏《{game['title']}》已回滚到 v{v['version']}", "/ugc")
    return get_game(game_id)


def retest(game_id: int) -> dict:
    v = latest_version(game_id)
    if v is None:
        raise KeyError("游戏不存在")
    meta = v["meta"].get("meta", v["meta"])
    slug = meta.get("slug", "retest")
    return _smoke(slug, Path(v["package_path"]), meta)


def delete_draft(game_id: int, owner_id: int) -> None:
    game = get_game(game_id)
    if game is None or game["owner_id"] != owner_id:
        raise KeyError("游戏不存在")
    if game["status"] != "draft":
        _reject("只有草稿可以删除")
    conn = _db()
    try:
        for v in _versions_of(game_id):
            _cleanup_dir(Path(v["package_path"]))
        conn.execute("DELETE FROM ugc_versions WHERE game_id = ?", (game_id,))
        conn.execute("DELETE FROM ugc_games WHERE id = ?", (game_id,))
        conn.commit()
    finally:
        conn.close()


def ban_user_games(user_id: int) -> None:
    """封禁作者联动（admin.set_user_status 调用）：其 UGC 全部下架。"""
    conn = _db()
    try:
        rows = conn.execute(
            "SELECT id, slug, status FROM ugc_games WHERE owner_id = ?",
            (user_id,)).fetchall()
    finally:
        conn.close()
    for gid, slug, status in rows:
        if status in ("published", "paused", "pending"):
            _set_game_status(gid, "banned")
            registry.unregister(slug)
            ugc_runner.drop_worker(slug)


def load_published_into_registry() -> int:
    """启动时把已公开游戏重新挂回注册表（内存态，重启后恢复）。"""
    conn = _db()
    try:
        rows = conn.execute(
            "SELECT id, slug, owner_id FROM ugc_games WHERE status = 'published'"
        ).fetchall()
    finally:
        conn.close()
    count = 0
    for gid, slug, owner_id in rows:
        v = active_version(gid)
        if v is None:
            continue
        try:
            _register_game({"id": gid, "slug": slug, "owner_id": owner_id}, v)
            count += 1
        except Exception:
            logging.getLogger(__name__).exception("failed to load published game %s", slug)
    return count
# ------------------------------------------------------------------ views

def _public_view(game: dict, version: dict | None, author: str) -> dict:
    out = {"id": game["id"], "slug": game["slug"], "title": game["title"],
           "description": game["description"], "author": author,
           "status": game["status"], "pause_reason": game["pause_reason"],
           "created_at": game["created_at"], "updated_at": game["updated_at"]}
    if version is not None:
        out["version"] = version["version"]
        out["version_status"] = version["status"]
        out["review_note"] = version["review_note"]
        out["changelog"] = version["changelog"]
        meta = dict(version["meta"].get("meta", version["meta"]))
        meta["renderer_enabled"] = bool(version["meta"].get("renderer_enabled"))
        out["meta"] = meta
        out["smoke"] = version["meta"].get("smoke")
        out["renderer_enabled"] = bool(version["meta"].get("renderer_enabled"))
        out["renderer_scan"] = version["meta"].get("renderer_scan")
    return out


def _author_name(user_id: int) -> str:
    conn = _db()
    try:
        r = conn.execute(
            "SELECT nickname, username FROM users WHERE id = ?",
            (user_id,)).fetchone()
    finally:
        conn.close()
    return (r[0] or r[1]) if r else f"user-{user_id}"


def list_my_games(owner_id: int) -> list[dict]:
    conn = _db()
    try:
        rows = conn.execute(
            "SELECT id FROM ugc_games WHERE owner_id = ? ORDER BY id DESC",
            (owner_id,)).fetchall()
    finally:
        conn.close()
    author = _author_name(owner_id)
    out = []
    for (gid,) in rows:
        g = get_game(gid)
        v = latest_version(gid)
        out.append(_public_view(g, v, author))
    return out


def list_public_games() -> list[dict]:
    conn = _db()
    try:
        rows = conn.execute(
            "SELECT id, owner_id FROM ugc_games WHERE status = 'published' "
            "ORDER BY id DESC").fetchall()
    finally:
        conn.close()
    out = []
    for gid, owner_id in rows:
        g = get_game(gid)
        out.append(_public_view(g, active_version(gid),
                               _author_name(owner_id)))
    return out


def review_queue() -> list[dict]:
    """审核队列：最新版本为 pending 的游戏（新游戏 + 新版本更新）。"""
    conn = _db()
    try:
        rows = conn.execute(
            "SELECT id, owner_id FROM ugc_games ORDER BY id DESC").fetchall()
    finally:
        conn.close()
    out = []
    for gid, owner_id in rows:
        v = latest_version(gid, statuses=["pending"])
        if v is None:
            continue
        g = get_game(gid)
        out.append(_public_view(g, v, _author_name(owner_id)))
    return out

def list_all_games() -> list[dict]:
    """管理后台：全部游戏（含作者名），最新在前。"""
    conn = _db()
    try:
        rows = conn.execute(
            "SELECT id, owner_id FROM ugc_games ORDER BY id DESC").fetchall()
    finally:
        conn.close()
    out = []
    for gid, owner_id in rows:
        g = get_game(gid)
        out.append(_public_view(g, latest_version(gid),
                               _author_name(owner_id)))
    return out







