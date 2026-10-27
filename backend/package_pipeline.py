"""Game package pipeline (L1, docs/design/19): what the server does to a
package's bytes, independent of who uploaded it or where it is in review.

    validate (zip + game.yaml) → extract → resource check → static scan
    → renderer scan → sandbox smoke            (ingest)
    extracted version dir → deterministic zip   (archive, for local training)

Review workflow, quotas, ownership and notifications live in ugc.py (L3).
Rejections raise ValueError with a user-facing (Chinese) message.
"""
from __future__ import annotations

import hashlib
import io
import shutil
import time
import zipfile
from pathlib import Path

import numpy as np
from gamekernel import scan as kernel_scan

import ugc_pack
import ugc_runner

SMOKE_STEPS = 20
_ARCHIVES: dict[str, tuple[bytes, str]] = {}   # package_path -> (zip, sha256)
_ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)


def cleanup_dir(dest: Path, root: Path) -> None:
    """Remove an extracted version dir, only ever inside ``root``."""
    if str(dest.resolve()).startswith(str(root.resolve())):
        shutil.rmtree(dest, ignore_errors=True)


def check_resources(dest: Path) -> None:
    """包内 .npz/.npy 资源必须可被 numpy 加载（12 §3 只读资源校验）。"""
    for pattern in ("*.npz", "*.npy"):
        for p in sorted(dest.rglob(pattern)):
            try:
                np.load(str(p), allow_pickle=False)
            except Exception as e:
                raise ValueError(f"资源文件损坏：{p.name}（{type(e).__name__}）")


def smoke(slug: str, game_dir: Path, meta: dict) -> dict:
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


def ingest(data: bytes, root: Path, *, taken_slugs, expect_slug: str | None = None,
           renderer_enabled: bool = False) -> tuple[dict, Path]:
    """校验 → 静态扫描 → 解包 → 资源校验 → 冒烟。返回 (stored_meta, extracted_dir)。

    ``taken_slugs``：已被占用的 slug（已注册游戏）；``expect_slug`` 为自家游戏的新版本。
    renderer_enabled 仅官方种子包置 True；UGC 由管理员审核后显式开启（16 §5.1）。
    """
    taken = set(taken_slugs)
    if expect_slug is not None:
        taken.discard(expect_slug)   # 自家已发布游戏的 slug 不算冲突
    report = ugc_pack.validate_package(data, builtin_games=taken)
    meta = report["meta"]
    if expect_slug is not None and meta["slug"] != expect_slug:
        raise ValueError(f"slug 不可更改（{expect_slug} → {meta['slug']}）")
    dest = root / meta["slug"] / f"v{int(time.time_ns())}"
    ugc_pack.extract_package(data, dest)
    try:
        check_resources(dest)
        scan = kernel_scan.scan_dir(dest)
        if not scan["ok"]:
            head = "; ".join(f"{v['file']}:{v['line']} {v['detail']}"
                             for v in scan["violations"][:3])
            raise ValueError(f"静态扫描未通过：{head}")
        rscan = None
        rend = meta.get("renderer")
        if rend:
            try:
                rtext = (dest / rend["entry"]).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                raise ValueError("渲染器文件不可读（需 UTF-8 文本）")
            rscan = kernel_scan.scan_renderer(rtext)
            if not rscan["ok"]:
                head = "; ".join(f"{v['line']} {v['detail']}"
                                 for v in rscan["violations"][:3])
                raise ValueError(f"渲染器静态扫描未通过：{head}")
        result = smoke(meta["slug"], dest, meta)
        if not result["ok"]:
            raise ValueError(f"沙箱冒烟失败：{result['error']}")
    except ValueError:
        cleanup_dir(dest, root)
        raise
    stored = {"meta": meta, "sha256": report["sha256"],
              "scan": scan, "renderer_scan": rscan, "smoke": result,
              "renderer_enabled": bool(rend) and renderer_enabled}
    return stored, dest


def archive(package_path: str | Path) -> tuple[bytes, str]:
    """已解包版本目录 → 确定性 zip（排序、固定时间戳与权限，去掉字节码）。
    版本目录按版本不可变，结果按 package_path 缓存。"""
    root = Path(package_path)
    key = str(root)
    if key not in _ARCHIVES:
        if not root.is_dir():
            raise KeyError("游戏包文件缺失")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in sorted(root.rglob("*")):
                if p.is_dir() or "__pycache__" in p.parts or p.suffix == ".pyc":
                    continue
                info = zipfile.ZipInfo(p.relative_to(root).as_posix(), _ZIP_EPOCH)
                info.external_attr = 0o644 << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                zf.writestr(info, p.read_bytes())
        data = buf.getvalue()
        _ARCHIVES[key] = (data, hashlib.sha256(data).hexdigest())
    return _ARCHIVES[key]
