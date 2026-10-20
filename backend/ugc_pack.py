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
import re
import zipfile
from pathlib import Path

import yaml

MAX_PACK_BYTES = 20 * 1024 * 1024
MAX_FILES = 200
ALLOWED_EXTS = {".py", ".json", ".yaml", ".yml", ".txt", ".md",
                ".npz", ".npy", ".bin",               # v2（12 §3）只读二进制资源
                ".png", ".webp", ".ogg", ".mp3", ".wav",  # 渲染 v2（16 §4）资源包
                ".js"}                                 # 渲染 v2（16 §5）沙箱渲染器
TEXT_EXTS = {".py", ".json", ".yaml", ".yml", ".txt", ".md", ".js"}
RESERVED_SLUGS = {"ugc"}   # our own frontend/API namespace; built-in games
                            # are added at call time from the registry
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
MAX_BOARD = 64

# ---- 渲染 v2（docs/design/16）常量 -----------------------------------------
MAX_ASSETS = 32
MAX_SOUNDS = 16
MAX_ASSET_BYTES = 256 * 1024
MAX_ASSETS_TOTAL = 2 * 1024 * 1024
MAX_SOUND_BYTES = 512 * 1024
MAX_IMAGE_DIM = 512
MAX_VECTOR_CHARS = 1024
MAX_RENDERER_BYTES = 128 * 1024
ALLOWED_IMAGE_EXTS = {".png", ".webp"}
ALLOWED_SOUND_EXTS = {".ogg", ".mp3", ".wav"}
RENDERER_FALLBACKS = {"declarative", "none"}
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,23}$")
PATH_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*|\.[0-9]+)*$")
VECTOR_PATH_RE = re.compile(r"^[Mm][MmLlHhVvCcSsQqTtAaZz0-9eE.,+\- ]*$")
IDLE_EFFECTS = {"pulse", "glow", "bob", "spin", "flicker", "float"}
ENTER_EFFECTS = {"pop", "fade", "flash", "rise"}
BOARD_EFFECTS = {"flash", "shake", "pulse", "dim", "tint"}
RENDER_ITEM_KEYS = {
    "glyph", "color", "bg", "glyph_color", "scale", "opacity", "shadow",
    "sprite", "vector", "orient", "anim", "enter", "z",
    "owner_colors", "owner_field", "hp", "label",
}


class UGCError(ValueError):
    """Upload rejected; the message is user-facing (Chinese)."""


def _err(msg: str) -> UGCError:
    return UGCError(msg)


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

def _str_field(meta: dict, key: str, lo: int, hi: int) -> str:
    v = meta.get(key)
    if not isinstance(v, str) or not v.strip():
        raise _err(f"game.yaml 缺少字段 {key}")
    v = v.strip()
    if not (lo <= len(v) <= hi):
        raise _err(f"{key} 长度需 {lo}-{hi} 字符")
    return v


# ---------------------------------------------------- 渲染 v2 字段校验（16）

def _hex_color(name: str, v) -> str:
    if not isinstance(v, str) or not HEX_RE.match(v):
        raise _err(f"{name} 需为 #rrggbb")
    return v.lower()


def _num(name: str, v, lo: float, hi: float, *, integer: bool = False):
    """数字字段：类型错误直接拒绝，越界夹紧（16 §3.7）。"""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise _err(f"{name} 需为数字")
    if integer and not float(v).is_integer():
        raise _err(f"{name} 需为整数")
    n = max(float(lo), min(float(hi), float(v)))
    return int(n) if integer else round(n, 4)


def _path_field(name: str, v) -> str:
    if (not isinstance(v, str) or len(v) > 64 or "__" in v
            or v.count(".") > 3 or not PATH_RE.match(v)):
        raise _err(f"{name} 需为 1-4 段字段路径（如 score / units.0.hp）")
    return v


def _asset_name(name: str, v) -> str:
    if not isinstance(v, str) or not NAME_RE.match(v):
        raise _err(f"{name} 需为小写字母/数字/_/-（1-24 字符）")
    return v


def _rel_file(name: str, v, exts: set, *, field: str = "file") -> str:
    if not isinstance(v, str) or not (1 <= len(v) <= 160):
        raise _err(f"{name}.{field} 需为包内相对路径")
    if (v.startswith(("/", "\\")) or ".." in Path(v).parts or "\\" in v
            or "\x00" in v or ":" in v.split("/")[0]):
        raise _err(f"{name}.{field} 非法路径：{v}")
    if Path(v).suffix.lower() not in exts:
        raise _err(f"{name}.{field} 类型不支持：{v}（仅 {'/'.join(sorted(exts))}）")
    return v


def _vector(name: str, v) -> dict:
    if not isinstance(v, dict) or set(v) - {"path", "color", "fill"}:
        raise _err(f"{name} 需为 {{path, color?, fill?}}")
    path = v.get("path")
    if (not isinstance(path, str) or not (1 <= len(path) <= MAX_VECTOR_CHARS)
            or not VECTOR_PATH_RE.match(path)):
        raise _err(f"{name}.path 需为 ≤{MAX_VECTOR_CHARS} 字符的 SVG 路径（M 开头）")
    out = {"path": path}
    if v.get("color") is not None:
        out["color"] = _hex_color(f"{name}.color", v["color"])
    if v.get("fill") is not None:
        if not isinstance(v["fill"], bool):
            raise _err(f"{name}.fill 需为布尔值")
        out["fill"] = v["fill"]
    return out


def _orient(name: str, v) -> dict:
    if not isinstance(v, dict) or set(v) - {"field", "angles"}:
        raise _err(f"{name} 需为 {{field, angles}}")
    field = _path_field(f"{name}.field", v.get("field"))
    angles = v.get("angles")
    if (not isinstance(angles, list) or not (2 <= len(angles) <= 8)
            or not all(isinstance(a, (int, float)) and not isinstance(a, bool)
                       for a in angles)):
        raise _err(f"{name}.angles 需 2-8 个角度（度）")
    return {"field": field,
            "angles": [round(float(a) % 360, 2) for a in angles]}


def _anim(name: str, v) -> dict:
    if not isinstance(v, dict) or set(v) - {"effect", "period", "amount"}:
        raise _err(f"{name} 需为 {{effect, period?, amount?}}")
    effect = v.get("effect")
    if effect not in IDLE_EFFECTS:
        raise _err(f"{name}.effect 需为 {'/'.join(sorted(IDLE_EFFECTS))}")
    out = {"effect": effect,
           "period": _num(f"{name}.period", v.get("period", 1000), 200, 5000,
                          integer=True)}
    if v.get("amount") is not None:
        out["amount"] = _num(f"{name}.amount", v["amount"], 0, 1)
    return out


def _enter(name: str, v) -> dict:
    if not isinstance(v, dict) or set(v) - {"effect", "ms"}:
        raise _err(f"{name} 需为 {{effect, ms?}}")
    effect = v.get("effect")
    if effect not in ENTER_EFFECTS:
        raise _err(f"{name}.effect 需为 {'/'.join(sorted(ENTER_EFFECTS))}")
    return {"effect": effect,
            "ms": _num(f"{name}.ms", v.get("ms", 200), 40, 1000, integer=True)}


def _board_effect(name: str, v) -> dict:
    if not isinstance(v, dict) or set(v) - {"kind", "ms", "color", "amount"}:
        raise _err(f"{name} 需为 {{kind, ms?, color?, amount?}}")
    kind = v.get("kind")
    if kind not in BOARD_EFFECTS:
        raise _err(f"{name}.kind 需为 {'/'.join(sorted(BOARD_EFFECTS))}")
    out = {"kind": kind,
           "ms": _num(f"{name}.ms", v.get("ms", 300), 80, 2000, integer=True)}
    if v.get("color") is not None:
        out["color"] = _hex_color(f"{name}.color", v["color"])
    if v.get("amount") is not None:
        out["amount"] = _num(f"{name}.amount", v["amount"], 0,
                             12 if kind == "shake" else 1)
    return out


def _render_item(name: str, v, *, require_visual: bool = True) -> dict:
    """palette / units / layers / miniboard 共用的渲染条目（16 §3.2）。"""
    if not isinstance(v, dict):
        raise _err(f"{name} 必须是映射（glyph/sprite/vector/…）")
    unknown = set(v) - RENDER_ITEM_KEYS
    if unknown:
        raise _err(f"{name} 存在未知字段：{', '.join(sorted(unknown))}")
    out: dict = {}
    if v.get("glyph") is not None:
        glyph = v["glyph"]
        if not isinstance(glyph, str) or not (1 <= len(glyph) <= 8):
            raise _err(f"{name}.glyph 需 1-8 字符")
        out["glyph"] = glyph
    for key in ("color", "bg", "glyph_color"):
        if v.get(key) is not None:
            out[key] = _hex_color(f"{name}.{key}", v[key])
    if v.get("scale") is not None:
        out["scale"] = _num(f"{name}.scale", v["scale"], 0.2, 2)
    if v.get("opacity") is not None:
        out["opacity"] = _num(f"{name}.opacity", v["opacity"], 0, 1)
    if v.get("shadow") is not None:
        if not isinstance(v["shadow"], bool):
            raise _err(f"{name}.shadow 需为布尔值")
        out["shadow"] = v["shadow"]
    if v.get("sprite") is not None:
        out["sprite"] = _asset_name(f"{name}.sprite", v["sprite"])
    if v.get("vector") is not None:
        out["vector"] = _vector(f"{name}.vector", v["vector"])
    if v.get("orient") is not None:
        out["orient"] = _orient(f"{name}.orient", v["orient"])
    if v.get("anim") is not None:
        out["anim"] = _anim(f"{name}.anim", v["anim"])
    if v.get("enter") is not None:
        out["enter"] = _enter(f"{name}.enter", v["enter"])
    if v.get("z") is not None:
        out["z"] = _num(f"{name}.z", v["z"], -10, 10, integer=True)
    if v.get("owner_colors") is not None:
        oc = v["owner_colors"]
        if not isinstance(oc, list) or not (2 <= len(oc) <= 4):
            raise _err(f"{name}.owner_colors 需 2-4 个颜色")
        out["owner_colors"] = [_hex_color(f"{name}.owner_colors[{i}]", c)
                               for i, c in enumerate(oc)]
    if v.get("owner_field") is not None:
        out["owner_field"] = _path_field(f"{name}.owner_field", v["owner_field"])
    if v.get("hp") is not None:
        hp = v["hp"]
        if not isinstance(hp, dict) or set(hp) - {"field", "max_field", "color"}:
            raise _err(f"{name}.hp 需为 {{field, max_field?, color?}}")
        hp_out = {"field": _path_field(f"{name}.hp.field", hp.get("field"))}
        if hp.get("max_field") is not None:
            hp_out["max_field"] = _path_field(f"{name}.hp.max_field", hp["max_field"])
        if hp.get("color") is not None:
            hp_out["color"] = _hex_color(f"{name}.hp.color", hp["color"])
        out["hp"] = hp_out
    if v.get("label") is not None:
        lb = v["label"]
        if not isinstance(lb, dict) or set(lb) - {"field"}:
            raise _err(f"{name}.label 需为 {{field}}")
        out["label"] = {"field": _path_field(f"{name}.label.field", lb.get("field"))}
    if require_visual and not any(k in out for k in ("glyph", "sprite", "vector")):
        raise _err(f"{name} 至少需要 glyph / sprite / vector 之一")
    return out


def _cell_spec(name: str, v) -> dict:
    if not isinstance(v, dict) or set(v) - {"size", "gap", "radius", "shape", "border"}:
        raise _err(f"{name} 需为 {{size, gap, radius, shape, border}}")
    out: dict = {}
    if v.get("size") is not None:
        out["size"] = _num(f"{name}.size", v["size"], 8, 64, integer=True)
    if v.get("gap") is not None:
        out["gap"] = _num(f"{name}.gap", v["gap"], 0, 8, integer=True)
    if v.get("radius") is not None:
        out["radius"] = _num(f"{name}.radius", v["radius"], 0, 24, integer=True)
    if v.get("shape") is not None:
        if v["shape"] not in ("square", "circle"):
            raise _err(f"{name}.shape 需为 square 或 circle")
        out["shape"] = v["shape"]
    if v.get("border") is not None:
        b = v["border"]
        if not isinstance(b, dict) or set(b) - {"color", "width"}:
            raise _err(f"{name}.border 需为 {{color?, width?}}")
        bo: dict = {}
        if b.get("color") is not None:
            bo["color"] = _hex_color(f"{name}.border.color", b["color"])
        if b.get("width") is not None:
            bo["width"] = _num(f"{name}.border.width", b["width"], 0, 4, integer=True)
        out["border"] = bo
    return out


def _background_spec(name: str, v) -> dict:
    if not isinstance(v, dict) or set(v) - {"kind", "color", "colors", "line"}:
        raise _err(f"{name} 需为 {{kind, color?, colors?, line?}}")
    kind = v.get("kind", "plain")
    if kind not in ("plain", "checker", "grid"):
        raise _err(f"{name}.kind 需为 plain/checker/grid")
    out = {"kind": kind}
    if v.get("color") is not None:
        out["color"] = _hex_color(f"{name}.color", v["color"])
    if v.get("colors") is not None:
        cs = v["colors"]
        if not isinstance(cs, list) or not (1 <= len(cs) <= 2):
            raise _err(f"{name}.colors 需为 1-2 个颜色")
        out["colors"] = [_hex_color(f"{name}.colors[{i}]", c)
                         for i, c in enumerate(cs)]
    if kind == "checker" and len(out.get("colors") or []) != 2:
        raise _err(f"{name}.colors 在 checker 下必填（2 色）")
    if v.get("line") is not None:
        out["line"] = _hex_color(f"{name}.line", v["line"])
    return out


def _palette_spec(name: str, v, *, require_visual: bool) -> dict:
    if not isinstance(v, dict) or not (1 <= len(v) <= 64):
        raise _err(f"{name} 需为 1-64 个 cell 定义")
    out = {}
    for cid, spec in v.items():
        if not isinstance(cid, str) or not (1 <= len(cid) <= 16):
            raise _err(f"{name} 键需为 1-16 字符的 cell id：{cid!r}")
        out[cid] = _render_item(f"{name}[{cid}]", spec,
                                require_visual=require_visual)
    return out


def _layer_spec(name: str, v) -> dict:
    if not isinstance(v, dict) or set(v) - {"field", "palette", "opacity"}:
        raise _err(f"{name} 需为 {{field, palette, opacity?}}")
    out = {"field": _path_field(f"{name}.field", v.get("field")),
           "palette": _palette_spec(f"{name}.palette", v.get("palette"),
                                    require_visual=False)}
    if v.get("opacity") is not None:
        out["opacity"] = _num(f"{name}.opacity", v["opacity"], 0, 1)
    return out


def _hud_item(name: str, v) -> dict:
    if not isinstance(v, dict):
        raise _err(f"{name} 需为映射")
    kind = v.get("kind")
    if kind not in ("stat", "bar", "badge", "text", "miniboard"):
        raise _err(f"{name}.kind 需为 stat/bar/badge/text/miniboard")
    unknown = set(v) - {"kind", "label", "path", "color", "max",
                        "width", "height", "cell", "palette"}
    if unknown:
        raise _err(f"{name} 存在未知字段：{', '.join(sorted(unknown))}")
    out = {"kind": kind, "path": _path_field(f"{name}.path", v.get("path"))}
    if v.get("label") is not None:
        lb = v["label"]
        if not isinstance(lb, str) or not (1 <= len(lb) <= 16):
            raise _err(f"{name}.label 需 1-16 字符")
        out["label"] = lb
    if v.get("color") is not None:
        out["color"] = _hex_color(f"{name}.color", v["color"])
    if kind == "bar":
        out["max"] = _num(f"{name}.max", v.get("max", 100), 1, 1e9, integer=True)
    if kind == "miniboard":
        out["width"] = _num(f"{name}.width", v.get("width", 4), 1, 16, integer=True)
        out["height"] = _num(f"{name}.height", v.get("height", 4), 1, 16, integer=True)
        if v.get("cell") is not None:
            out["cell"] = _num(f"{name}.cell", v["cell"], 8, 32, integer=True)
        out["palette"] = _palette_spec(f"{name}.palette", v.get("palette"),
                                       require_visual=False)
    return out


def _assets_spec(meta: dict, files) -> dict:
    assets = meta.get("assets")
    if assets is None:
        return {}
    if not isinstance(assets, dict) or not (1 <= len(assets) <= MAX_ASSETS):
        raise _err(f"assets 需为 1-{MAX_ASSETS} 个资源定义")
    out = {}
    for key, spec in assets.items():
        if not isinstance(key, str) or not NAME_RE.match(key):
            raise _err(f"assets 键需为小写字母/数字/_/-（1-24 字符）：{key!r}")
        if not isinstance(spec, dict) or set(spec) - {"file", "w", "h"}:
            raise _err(f"assets[{key}] 需为 {{file, w?, h?}}")
        item = {"file": _rel_file(f"assets[{key}]", spec.get("file"),
                                  ALLOWED_IMAGE_EXTS)}
        if files is not None and item["file"] not in files:
            raise _err(f"assets[{key}].file 不存在于包内：{item['file']}")
        for dim in ("w", "h"):
            if spec.get(dim) is not None:
                item[dim] = _num(f"assets[{key}].{dim}", spec[dim], 1,
                                 MAX_IMAGE_DIM, integer=True)
        out[key] = item
    return out


def _sounds_spec(meta: dict, files) -> dict:
    sounds = meta.get("sounds")
    if sounds is None:
        return {}
    if not isinstance(sounds, dict) or not (1 <= len(sounds) <= MAX_SOUNDS):
        raise _err(f"sounds 需为 1-{MAX_SOUNDS} 个音效定义")
    out = {}
    for key, spec in sounds.items():
        if not isinstance(key, str) or not NAME_RE.match(key):
            raise _err(f"sounds 键需为小写字母/数字/_/-（1-24 字符）：{key!r}")
        if not isinstance(spec, dict) or set(spec) - {"file", "ms", "volume"}:
            raise _err(f"sounds[{key}] 需为 {{file, ms?, volume?}}")
        item = {"file": _rel_file(f"sounds[{key}]", spec.get("file"),
                                  ALLOWED_SOUND_EXTS)}
        if files is not None and item["file"] not in files:
            raise _err(f"sounds[{key}].file 不存在于包内：{item['file']}")
        item["ms"] = _num(f"sounds[{key}].ms", spec.get("ms", 600), 10, 5000,
                          integer=True)
        item["volume"] = _num(f"sounds[{key}].volume",
                              spec.get("volume", 0.8), 0, 1)
        out[key] = item
    return out


def _renderer_spec(meta: dict, files) -> dict:
    rend = meta.get("renderer")
    if rend is None:
        return {}
    if not isinstance(rend, dict) or set(rend) - {"entry", "protocol", "fallback"}:
        raise _err("renderer 需为 {entry, protocol?, fallback?} 映射")
    entry = _rel_file("renderer", rend.get("entry"), {".js"}, field="entry")
    if files is not None and entry not in files:
        raise _err(f"renderer.entry 不存在于包内：{entry}")
    if rend.get("protocol", 1) != 1 or isinstance(rend.get("protocol"), bool):
        raise _err("renderer.protocol 只支持 1")
    fallback = rend.get("fallback", "declarative")
    if fallback not in RENDERER_FALLBACKS:
        raise _err("renderer.fallback 需为 declarative 或 none")
    return {"entry": entry, "protocol": 1, "fallback": fallback}


# ------------------------------------------------------ 资源字节校验（16 §4.2）

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


def _shape(name: str, v) -> list[int]:
    if (not isinstance(v, list) or not (1 <= len(v) <= 4)
            or not all(isinstance(d, int) and 1 <= d <= 4096 for d in v)):
        raise _err(f"{name} 需为 1-4 维正整数列表")
    return [int(d) for d in v]


def validate_meta(meta, builtin_games=None, files=None) -> dict:
    """Normalize + validate the game.yaml mapping. Unknown top-level keys
    are rejected (typo protection). files（包内文件名列表）用于校验
    assets/sounds/renderer 的引用完整性；缺省时跳过存在性检查。
    Returns the normalized meta dict."""
    builtin = set(builtin_games or ())
    if not isinstance(meta, dict):
        raise _err("game.yaml 必须是映射（顶层键：slug/title/…）")
    known = {"slug", "title", "description", "version", "board", "units",
             "contract", "ai_strategies", "pvp", "opponents",
             "default_opponent", "controls",
             "assets", "sounds", "renderer"}   # v2（12 §3）+ 渲染 v2（16）
    unknown = set(meta) - known
    if unknown:
        raise _err(f"game.yaml 存在未知字段：{', '.join(sorted(unknown))}")

    slug = _str_field(meta, "slug", 2, 40)
    if not SLUG_RE.match(slug):
        raise _err("slug 只能是小写字母/数字/连字符（2-40 字符，字母或数字开头）")
    if slug in RESERVED_SLUGS or slug in builtin:
        raise _err(f"slug {slug!r} 已被占用（内置游戏或保留名）")
    title = _str_field(meta, "title", 1, 40)
    description = _str_field(meta, "description", 1, 200)
    version = _str_field(meta, "version", 1, 24)
    if not VERSION_RE.match(version):
        raise _err("version 需为 x.y.z 格式")

    board = meta.get("board")
    if not isinstance(board, dict):
        raise _err("缺少 board 声明（渲染器必需）")
    unknown = set(board) - {"schema", "renderer", "width", "height", "cell",
                            "background", "palette", "layers", "hud", "events"}
    if unknown:
        raise _err(f"board 存在未知字段：{', '.join(sorted(unknown))}")
    schema = board.get("schema", 2)
    if isinstance(schema, bool) or schema not in (1, 2):
        raise _err("board.schema 需为 1 或 2")
    w, h = board.get("width"), board.get("height")
    if (not isinstance(w, int) or isinstance(w, bool)
            or not isinstance(h, int) or isinstance(h, bool)
            or not (1 <= w <= MAX_BOARD) or not (1 <= h <= MAX_BOARD)):
        raise _err(f"board.width/height 需为 1-{MAX_BOARD} 的整数")
    palette = _palette_spec("board.palette", board.get("palette"),
                            require_visual=False)
    b_out = {"schema": int(schema), "width": int(w), "height": int(h),
             "palette": palette}
    if board.get("renderer") is not None:
        if board["renderer"] not in ("auto", "dom", "canvas"):
            raise _err("board.renderer 需为 auto/dom/canvas")
        b_out["renderer"] = board["renderer"]
    if board.get("cell") is not None:
        b_out["cell"] = _cell_spec("board.cell", board["cell"])
    if board.get("background") is not None:
        b_out["background"] = _background_spec("board.background",
                                               board["background"])
    if board.get("layers") is not None:
        layers = board["layers"]
        if not isinstance(layers, list) or not (1 <= len(layers) <= 4):
            raise _err("board.layers 需为 1-4 层叠加定义")
        b_out["layers"] = [_layer_spec(f"board.layers[{i}]", it)
                           for i, it in enumerate(layers)]
    if board.get("hud") is not None:
        hud = board["hud"]
        if not isinstance(hud, list) or not (1 <= len(hud) <= 8):
            raise _err("board.hud 需为 1-8 项")
        b_out["hud"] = [_hud_item(f"board.hud[{i}]", it)
                        for i, it in enumerate(hud)]
    if board.get("events") is not None:
        evs = board["events"]
        if not isinstance(evs, list) or not (1 <= len(evs) <= 8):
            raise _err("board.events 需为 1-8 条")
        ev_out = []
        for i, it in enumerate(evs):
            if not isinstance(it, dict) or set(it) - {"name", "effect", "sound"}:
                raise _err(f"board.events[{i}] 需为 {{name, effect, sound?}}")
            name = it.get("name")
            if not isinstance(name, str) or not (1 <= len(name) <= 24):
                raise _err(f"board.events[{i}].name 需 1-24 字符")
            item = {"name": name,
                    "effect": _board_effect(f"board.events[{i}].effect",
                                            it.get("effect"))}
            if it.get("sound") is not None:
                item["sound"] = _asset_name(f"board.events[{i}].sound",
                                            it["sound"])
            ev_out.append(item)
        b_out["events"] = ev_out
    out = {"slug": slug, "title": title, "description": description,
           "version": version, "board": b_out}

    units = meta.get("units")
    if units is not None:
        if not isinstance(units, dict) or not (1 <= len(units) <= 32):
            raise _err("units 需为 1-32 个单位类型定义")
        out["units"] = {k: _render_item(f"units[{k}]", v)
                        for k, v in units.items()}

    assets = _assets_spec(meta, files)
    if assets:
        out["assets"] = assets
    sounds = _sounds_spec(meta, files)
    if sounds:
        out["sounds"] = sounds

    def _check_sprite(label, item):
        sp = item.get("sprite")
        if sp and sp not in assets:
            raise _err(f"{label}.sprite 未在 assets 中声明：{sp}")

    for cid, item in palette.items():
        _check_sprite(f"palette[{cid}]", item)
    for key, item in (out.get("units") or {}).items():
        _check_sprite(f"units[{key}]", item)
    for i, layer in enumerate(b_out.get("layers") or []):
        for cid, item in layer["palette"].items():
            _check_sprite(f"board.layers[{i}].palette[{cid}]", item)
    for i, item in enumerate(b_out.get("hud") or []):
        for cid, spec in (item.get("palette") or {}).items():
            _check_sprite(f"board.hud[{i}].palette[{cid}]", spec)
    for i, ev in enumerate(b_out.get("events") or []):
        snd = ev.get("sound")
        if snd and snd not in sounds:
            raise _err(f"board.events[{i}].sound 未在 sounds 中声明：{snd}")

    rend = _renderer_spec(meta, files)
    if rend:
        out["renderer"] = rend

    contract = meta.get("contract")
    if contract is not None:
        if not isinstance(contract, dict):
            raise _err("contract 需为 {in_shape, out_shape, protocol?} 映射")
        protocol = contract.get("protocol", "simple")
        if protocol not in ("simple", "composite"):
            raise _err("contract.protocol 需为 simple 或 composite")
        obs_mode = contract.get("obs_mode")
        if obs_mode is not None and (not isinstance(obs_mode, str)
                                     or not (1 <= len(obs_mode) <= 24)):
            raise _err("contract.obs_mode 需为 1-24 字符的观测模式名")
        out["contract"] = {
            "in_shape": _shape("contract.in_shape", contract.get("in_shape")),
            "out_shape": _shape("contract.out_shape", contract.get("out_shape")),
            "protocol": protocol,
        }
        if obs_mode is not None:
            out["contract"]["obs_mode"] = obs_mode

    strategies = meta.get("ai_strategies")
    if strategies is not None:
        if (not isinstance(strategies, list) or not (1 <= len(strategies) <= 16)
                or not all(isinstance(s, str) and 1 <= len(s) <= 24
                           for s in strategies)):
            raise _err("ai_strategies 需为 1-16 个策略名（各 1-24 字符）")
        out["ai_strategies"] = list(strategies)

    pvp = meta.get("pvp")
    if pvp is not None:
        if not isinstance(pvp, dict):
            raise _err("pvp 需为 {enabled, action, choices?} 映射")
        enabled = pvp.get("enabled", False)
        if not isinstance(enabled, bool):
            raise _err("pvp.enabled 需为布尔值")
        action = pvp.get("action", "unit")
        if action not in ("unit", "choice"):
            raise _err("pvp.action 需为 unit 或 choice")
        pvp_out = {"enabled": bool(enabled), "action": action}
        if action == "choice":
            choices = pvp.get("choices")
            if (not isinstance(choices, list) or not (2 <= len(choices) <= 16)
                    or not all(isinstance(c, str) and 1 <= len(c) <= 24
                               for c in choices)):
                raise _err("pvp.choice 需声明 2-16 个选项（各 1-24 字符）")
            pvp_out["choices"] = list(choices)
        options = pvp.get("options")
        if options is not None:
            if not isinstance(options, dict) or not all(
                    isinstance(k, str) for k in options):
                raise _err("pvp.options 需为字符串键的映射（开局附加参数）")
            pvp_out["options"] = options
        out["pvp"] = pvp_out

    opponents = meta.get("opponents")
    if opponents is not None:
        if (not isinstance(opponents, list) or not (1 <= len(opponents) <= 16)
                or not all(isinstance(s, str) and 1 <= len(s) <= 24
                           for s in opponents)):
            raise _err("opponents 需为 1-16 个策略名（各 1-24 字符）")
        out["opponents"] = list(opponents)

    default_opponent = meta.get("default_opponent")
    if default_opponent is not None:
        if not isinstance(default_opponent, str) \
                or not (1 <= len(default_opponent) <= 24):
            raise _err("default_opponent 需为 1-24 字符的策略名")
        if opponents is not None and default_opponent not in opponents:
            raise _err("default_opponent 必须在 opponents 列表中")
        out["default_opponent"] = default_opponent

    controls = meta.get("controls")
    if controls is not None:
        if not isinstance(controls, dict):
            raise _err("controls 需为 {mode, keys, direction_field?} 映射")
        mode = controls.get("mode")
        if mode not in ("absolute", "relative-turn"):
            raise _err("controls.mode 需为 absolute 或 relative-turn")
        c_out = {"mode": mode}
        if mode == "relative-turn":
            df = controls.get("direction_field")
            if not isinstance(df, str) or not (1 <= len(df) <= 24):
                raise _err("controls.direction_field 需声明 state 中的朝向字段")
            c_out["direction_field"] = df
        keys = controls.get("keys")
        if not isinstance(keys, dict) or not (1 <= len(keys) <= 16):
            raise _err("controls.keys 需为 1-16 个按键映射")
        for k, v in keys.items():
            if not isinstance(k, str) or not (1 <= len(k) <= 24):
                raise _err(f"controls.keys 键名非法：{k!r}")
            if (not isinstance(v, list) or len(v) != 2
                    or not isinstance(v[0], int)
                    or not isinstance(v[1], str) or not (1 <= len(v[1]) <= 8)):
                raise _err(f"controls.keys[{k}] 需为 [动作值, 标签]")
            c_out["keys"] = c_out.get("keys", {})
            c_out["keys"][k] = [int(v[0]), v[1]]
        out["controls"] = c_out
    return out


