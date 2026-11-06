"""UGC package validation (11 P1): zip structure + game.yaml schema + safe
extraction. This is the FIRST security layer of docs/design/10 §5.

- zip safety: size/file-count caps, extension whitelist (text-only, no
  binaries), path traversal / symlink / zip-bomb checks, UTF-8 enforcement
- game.yaml: strict schema (unknown keys rejected so typos surface early)
- slug: globally unique, immutable, never colliding with built-in games
"""
from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path

import yaml
from gamekernel.manifest import (  # noqa: F401  (limits re-exported for asset routes)
    ALLOWED_EXTS, ALLOWED_IMAGE_EXTS, ALLOWED_SOUND_EXTS, MAX_ASSET_BYTES,
    MAX_ASSETS_TOTAL, MAX_FILES, MAX_IMAGE_DIM, MAX_PACK_BYTES, MAX_RENDERER_BYTES,
    MAX_SOUND_BYTES, TEXT_EXTS, ManifestError as UGCError, _err, validate_meta,
)

# ---------------------------------------------------------------- zip layer

def validate_package(data: bytes, builtin_games=None) -> dict:
    """Validate a zip byte string end to end.

    Returns {"sha256", "size", "files", "meta"} where meta is the
    normalized game.yaml dict. Raises UGCError on any violation.
    """
    builtin = set(builtin_games or ())
    if len(data) > MAX_PACK_BYTES:
        raise _err(f"包超过 {MAX_PACK_BYTES // (1024 * 1024)}MB 限制")
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise _err("不是有效的 zip 包")
    with zf:
        names = zf.namelist()
        if len([n for n in names if not n.endswith("/")]) > MAX_FILES:
            raise _err(f"文件数超过 {MAX_FILES} 个")
        for n in names:
            parts = Path(n).parts
            # 拒绝绝对路径、跨目录与 Windows 盘符/ADS（首段含冒号）
            if (n.startswith(("/", "\\")) or ".." in parts
                    or "\x00" in n or ":" in n.split("/")[0]):
                raise _err(f"非法路径：{n}")
            if n.endswith("/"):
                continue  # directory entry
            ext = Path(n).suffix.lower()
            if ext not in ALLOWED_EXTS:
                raise _err("不允许的文件类型：" + n +
                           "（仅 .py/.json/.yaml/.txt/.md/.npz/.npy/.bin）")
            info = zf.getinfo(n)
            mode = (info.external_attr >> 16) & 0o170000
            if mode == 0o120000:
                raise _err(f"包内不允许符号链接：{n}")
            if info.file_size > MAX_PACK_BYTES:
                raise _err(f"文件过大：{n}")
            if ext in TEXT_EXTS:
                try:
                    zf.read(n).decode("utf-8")
                except UnicodeDecodeError:
                    raise _err(f"文件不是 UTF-8 文本：{n}")
        if "__init__.py" not in names:
            raise _err("缺少 __init__.py（需暴露 get_adapter()）")
        if "game.yaml" not in names:
            raise _err("缺少 game.yaml")
        meta_raw = zf.read("game.yaml").decode("utf-8")
        try:
            meta = yaml.safe_load(meta_raw)
        except yaml.YAMLError as e:
            raise _err(f"game.yaml 解析失败：{e}")
        files = sorted(n for n in names if not n.endswith("/"))
        meta = validate_meta(meta, builtin, files=files)
        _validate_asset_bytes(zf, meta)
        # 图片/音效/渲染器文件必须显式声明（未声明的一律拒绝，16 §4.1）
        declared = {spec["file"] for spec in (meta.get("assets") or {}).values()}
        declared |= {spec["file"] for spec in (meta.get("sounds") or {}).values()}
        if meta.get("renderer"):
            declared.add(meta["renderer"]["entry"])
        resource_exts = ALLOWED_IMAGE_EXTS | ALLOWED_SOUND_EXTS | {".js"}
        for n in files:
            if Path(n).suffix.lower() in resource_exts and n not in declared:
                raise _err(f"未声明的资源文件：{n}（需在 assets/sounds/renderer 中声明）")
    return {
        "sha256": hashlib.sha256(data).hexdigest(),
        "size": len(data),
        "files": sorted(n for n in names if not n.endswith("/")),
        "meta": meta,
    }


def extract_package(data: bytes, dest: Path) -> dict:
    """Validate, then extract into dest (created if missing). Returns the
    same dict as validate_package. Extraction re-runs the same safety checks.
    """
    report = validate_package(data)
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for n in zf.namelist():
            if n.endswith("/"):
                continue
            target = (dest / n).resolve()
            if not str(target).startswith(str(dest.resolve())):
                raise _err(f"非法路径：{n}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(zf.read(n))
    return report
# -------------------------------------------------------------- meta schema

def _sniff_image(name: str, data: bytes) -> tuple:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        if len(data) < 24 or data[12:16] != b"IHDR":
            raise _err(f"图片损坏：{name}")
        return ("png", int.from_bytes(data[16:20], "big"),
                int.from_bytes(data[20:24], "big"))
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        if len(data) < 30:
            raise _err(f"图片损坏：{name}")
        fourcc = data[12:16]
        if fourcc == b"VP8X":
            return ("webp", 1 + int.from_bytes(data[24:27], "little"),
                    1 + int.from_bytes(data[27:30], "little"))
        if fourcc == b"VP8 ":
            if data[23:26] != b"\x9d\x01\x2a":
                raise _err(f"图片损坏：{name}")
            return ("webp", int.from_bytes(data[26:28], "little") & 0x3FFF,
                    int.from_bytes(data[28:30], "little") & 0x3FFF)
        if fourcc == b"VP8L":
            if data[20] != 0x2F:
                raise _err(f"图片损坏：{name}")
            bits = int.from_bytes(data[21:25], "little")
            return ("webp", (bits & 0x3FFF) + 1,
                    ((bits >> 14) & 0x3FFF) + 1)
        raise _err(f"不支持的 WebP 编码：{name}")
    raise _err(f"图片魔数不合法（仅 PNG/WebP）：{name}")


def _sniff_audio(name: str, data: bytes) -> str:
    if data[:4] == b"OggS":
        return "ogg"
    if data[:3] == b"ID3":
        return "mp3"
    if len(data) >= 2 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0:
        return "mp3"
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "wav"
    raise _err(f"音频魔数不合法（仅 OGG/MP3/WAV）：{name}")


def _validate_asset_bytes(zf, meta: dict) -> None:
    """按声明读取资源并校验魔数/尺寸/体积（16 §4.1）。"""
    total = 0
    for key, spec in (meta.get("assets") or {}).items():
        try:
            data = zf.read(spec["file"])
        except KeyError:
            raise _err(f"assets[{key}].file 不存在于包内：{spec['file']}")
        if len(data) > MAX_ASSET_BYTES:
            raise _err(f"图片过大：{spec['file']}（≤{MAX_ASSET_BYTES // 1024}KB）")
        total += len(data)
        if total > MAX_ASSETS_TOTAL:
            raise _err(f"图片资源合计超过 {MAX_ASSETS_TOTAL // (1024 * 1024)}MB")
        _kind, w, h = _sniff_image(spec["file"], data)
        if w > MAX_IMAGE_DIM or h > MAX_IMAGE_DIM:
            raise _err(f"图片尺寸过大：{spec['file']}（{w}x{h}，单边 ≤{MAX_IMAGE_DIM}）")
    for key, spec in (meta.get("sounds") or {}).items():
        try:
            data = zf.read(spec["file"])
        except KeyError:
            raise _err(f"sounds[{key}].file 不存在于包内：{spec['file']}")
        if len(data) > MAX_SOUND_BYTES:
            raise _err(f"音效过大：{spec['file']}（≤{MAX_SOUND_BYTES // 1024}KB）")
        _sniff_audio(spec["file"], data)
    rend = meta.get("renderer")
    if rend:
        try:
            data = zf.read(rend["entry"])
        except KeyError:
            raise _err(f"renderer.entry 不存在于包内：{rend['entry']}")
        if len(data) > MAX_RENDERER_BYTES:
            raise _err(f"渲染器过大：{rend['entry']}（≤{MAX_RENDERER_BYTES // 1024}KB）")
