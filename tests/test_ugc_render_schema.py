"""渲染 v2 schema 测试（设计 16）：board 扩展 / 渲染条目 / 资源 / 渲染器声明。"""
import io
import sys
import zipfile
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

import ugc_pack  # noqa: E402

BASE = """slug: render-demo
title: 渲染示例
description: 测试渲染 v2 校验
version: 1.0.0
board:
  width: 4
  height: 4
  palette:
    empty: { color: "#f1f5f9" }
    body:  { color: "#22c55e", glyph: "●" }
"""


def _zip(files) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            data = content.encode() if isinstance(content, str) else content
            zf.writestr(name, data)
    return buf.getvalue()


def _pack(meta=BASE, **files) -> bytes:
    all_files = {
        "game.yaml": meta,
        "__init__.py": "def get_adapter():\n    raise NotImplementedError\n",
    }
    all_files.update(files)
    return _zip(all_files)


def _png(w=2, h=3) -> bytes:
    """仅含签名 + IHDR 的合法头（校验器只看这两处）。"""
    return (b"\x89PNG\r\n\x1a\n" + (13).to_bytes(4, "big") + b"IHDR"
            + w.to_bytes(4, "big") + h.to_bytes(4, "big")
            + b"\x08\x06\x00\x00\x00" + b"\x00" * 8)


def _webp_vp8x(w=4, h=5) -> bytes:
    return (b"RIFF" + (22).to_bytes(4, "little") + b"WEBP" + b"VP8X"
            + (10).to_bytes(4, "little") + b"\x00" * 4
            + (w - 1).to_bytes(3, "little") + (h - 1).to_bytes(3, "little"))


FULL = BASE + """
  cell: { size: 32, gap: 1, radius: 6, shape: circle,
          border: { color: "#e4e4e7", width: 1 } }
  background: { kind: checker, colors: ["#ffffff", "#f1f5f9"] }
  palette:
    empty: { color: "#f1f5f9" }
    body:  { color: "#22c55e", glyph: "●", glyph_color: "#ffffff", scale: 0.8,
             opacity: 0.95, shadow: true, enter: { effect: pop, ms: 150 } }
    head:  { sprite: head, orient: { field: direction, angles: [270, 90, 180, 0] } }
    food:  { vector: { path: "M1 1L9 9", color: "#ef4444", fill: false },
             anim: { effect: pulse, period: 1200, amount: 0.2 }, z: 2 }
  layers:
    - { field: overlay, palette: { fog: { color: "#0f172a", opacity: 0.4 } } }
  hud:
    - { kind: stat, label: 分数, path: score }
    - { kind: bar, label: 能量, path: energy, max: 100, color: "#4f46e5" }
    - { kind: miniboard, label: NEXT, path: next_board, width: 4, height: 4,
        cell: 16, palette: { "0": { color: "#f1f5f9" }, "1": { color: "#00b8d9" } } }
  events:
    - { name: eat, effect: { kind: flash, color: "#22c55e", ms: 260 }, sound: eat }
    - { name: death, effect: { kind: shake, ms: 400, amount: 6 } }
units:
  worker:
    glyph: "👷"
    owner_colors: ["#2563eb", "#dc2626"]
    owner_field: owner
    hp: { field: hp, max_field: hp_max, color: "#22c55e" }
    label: { field: tag }
    z: 1
assets:
  head: { file: "assets/head.png", w: 2, h: 3 }
sounds:
  eat: { file: "assets/eat.ogg", ms: 400, volume: 0.6 }
renderer:
  entry: renderer.js
  protocol: 1
  fallback: declarative
"""


def test_full_v2_package_passes():
    rep = ugc_pack.validate_package(_pack(
        FULL, **{"assets/head.png": _png(), "assets/eat.ogg": b"OggS\x00\x02",
                 "renderer.js": "globalThis.Renderer = { frame() {} };\n"}))
    m = rep["meta"]
    assert m["board"]["schema"] == 2
    assert m["board"]["cell"]["size"] == 32
    assert m["board"]["cell"]["shape"] == "circle"
    assert m["board"]["background"]["colors"] == ["#ffffff", "#f1f5f9"]
    assert m["board"]["palette"]["head"]["orient"]["angles"] == [270.0, 90.0, 180.0, 0.0]
    assert m["board"]["palette"]["food"]["vector"]["fill"] is False
    assert m["board"]["layers"][0]["field"] == "overlay"
    assert m["board"]["hud"][1]["max"] == 100
    assert m["board"]["hud"][2]["width"] == 4
    assert m["board"]["events"][0]["sound"] == "eat"
    assert m["units"]["worker"]["owner_colors"] == ["#2563eb", "#dc2626"]
    assert m["units"]["worker"]["hp"]["field"] == "hp"
    assert m["assets"]["head"] == {"file": "assets/head.png", "w": 2, "h": 3}
    assert m["sounds"]["eat"]["volume"] == 0.6
    assert m["renderer"] == {"entry": "renderer.js", "protocol": 1,
                             "fallback": "declarative"}


def test_v1_meta_still_normalizes_identically():
    rep = ugc_pack.validate_package(_pack())
    m = rep["meta"]
    assert m["board"]["schema"] == 2          # 缺省按 2，但无新字段
    assert m["board"]["palette"]["empty"] == {"color": "#f1f5f9"}
    assert m["board"]["palette"]["body"] == {"color": "#22c55e", "glyph": "●"}
    assert "cell" not in m["board"] and "hud" not in m["board"]
    assert "assets" not in m and "renderer" not in m


def test_schema_version_and_unknown_fields():
    bad = [
        (BASE.replace("  width: 4", "  schema: 3\n  width: 4"), "schema"),
        (BASE.replace("  width: 4", "  nope: 1\n  width: 4"), "未知字段"),
        (BASE.replace("  width: 4", "  renderer: webgl\n  width: 4"), "auto/dom/canvas"),
        (BASE + "  cell: { shape: hex }\n", "square 或 circle"),
        (BASE + "  background: { kind: stripes }\n", "plain/checker/grid"),
        (BASE + "  background: { kind: checker }\n", "必填"),
    ]
    for meta, frag in bad:
        with pytest.raises(ugc_pack.UGCError, match=frag):
            ugc_pack.validate_package(_pack(meta))


def test_render_item_validation():
    bad = [
        (BASE.replace('body:  { color: "#22c55e", glyph: "●" }',
                      'body:  { glyph: "●", nope: 1 }'), "未知字段"),
        (BASE.replace('body:  { color: "#22c55e", glyph: "●" }',
                      'body:  { glyph: "●", scale: "big" }'), "数字"),
        (BASE.replace('body:  { color: "#22c55e", glyph: "●" }',
                      'body:  { glyph: "●", anim: { effect: explode } }'), "effect"),
        (BASE.replace('body:  { color: "#22c55e", glyph: "●" }',
                      'body:  { glyph: "●", enter: { effect: spin } }'), "effect"),
        (BASE.replace('body:  { color: "#22c55e", glyph: "●" }',
                      'body:  { glyph: "●", vector: { path: "not a path" } }'), "SVG"),
        (BASE.replace('body:  { color: "#22c55e", glyph: "●" }',
                      'body:  { glyph: "●", orient: { field: "a..b", angles: [0, 90] } }'), "字段路径"),
        (BASE.replace('body:  { color: "#22c55e", glyph: "●" }',
                      'body:  { glyph: "●", hp: { max_field: "x" } }'), "字段路径"),
        (BASE.replace('body:  { color: "#22c55e", glyph: "●" }',
                      'body:  { glyph: "●", hp: { field: "x", nope: 1 } }'), "hp"),
        (BASE + "units:\n  u: { color: \"#000000\" }\n", "glyph / sprite / vector"),
        (BASE + "units:\n  u: { glyph: \"x\", owner_colors: [\"#000000\"] }\n", "2-4"),
    ]
    for meta, frag in bad:
        with pytest.raises(ugc_pack.UGCError, match=frag):
            ugc_pack.validate_package(_pack(meta))

    # 数字越界夹紧（16 §3.7）
    clamped = BASE.replace('body:  { color: "#22c55e", glyph: "●" }',
                           'body:  { glyph: "●", scale: 9, opacity: -1, z: 99 }')
    m = ugc_pack.validate_package(_pack(clamped))["meta"]
    assert m["board"]["palette"]["body"]["scale"] == 2
    assert m["board"]["palette"]["body"]["opacity"] == 0
    assert m["board"]["palette"]["body"]["z"] == 10


def test_hud_and_layer_validation():
    bad = [
        (BASE + "  hud: [{ kind: donut, path: score }]\n", "stat/bar/badge/text/miniboard"),
        (BASE + "  hud: [{ kind: stat }]\n", "字段路径"),
        (BASE + "  hud: [{ kind: stat, path: score, nope: 1 }]\n", "未知字段"),
        (BASE + "  hud: [{ kind: miniboard, path: next }]\n", "palette"),
        (BASE + "  layers: [{ field: overlay }]\n", "palette"),
        (BASE + "  events: [{ name: eat, effect: { kind: boom } }]\n", "kind"),
        (BASE + "  events: [{ name: eat }]\n", "effect"),
    ]
    for meta, frag in bad:
        with pytest.raises(ugc_pack.UGCError, match=frag):
            ugc_pack.validate_package(_pack(meta))
    ok = BASE + """  hud:
    - { kind: badge, label: 等级, path: level, color: "#4f46e5" }
    - { kind: text, label: 状态, path: status }
"""
    assert len(ugc_pack.validate_package(_pack(ok))["meta"]["board"]["hud"]) == 2


def test_resource_reference_integrity():
    with pytest.raises(ugc_pack.UGCError, match="sprite"):
        ugc_pack.validate_package(_pack(BASE + '  palette:\n    x: { sprite: ghost }\n'))
    with pytest.raises(ugc_pack.UGCError, match="sound"):
        ugc_pack.validate_package(_pack(
            BASE + "  events: [{ name: eat, effect: { kind: flash }, sound: nope }]\n"))
    with pytest.raises(ugc_pack.UGCError, match="不存在于包内"):
        ugc_pack.validate_package(_pack(BASE + 'assets:\n  a: { file: "assets/a.png" }\n'))


def test_asset_bytes_sniffing():
    decl = BASE + 'assets:\n  a: { file: "assets/a.png" }\n'
    # 合法 PNG / WebP 通过
    ugc_pack.validate_package(_pack(decl, **{"assets/a.png": _png()}))
    ugc_pack.validate_package(_pack(
        BASE + 'assets:\n  a: { file: "assets/a.webp" }\n',
        **{"assets/a.webp": _webp_vp8x()}))
    # 伪造扩展名 / 魔数不合法
    with pytest.raises(ugc_pack.UGCError, match="魔数"):
        ugc_pack.validate_package(_pack(decl, **{"assets/a.png": b"GIF89a\x00"}))
    # 尺寸超限
    with pytest.raises(ugc_pack.UGCError, match="尺寸过大"):
        ugc_pack.validate_package(_pack(
            BASE + 'assets:\n  a: { file: "assets/a.png" }\n',
            **{"assets/a.png": _png(1024, 8)}))
    # 单文件超限
    with pytest.raises(ugc_pack.UGCError, match="图片过大"):
        ugc_pack.validate_package(_pack(
            BASE + 'assets:\n  a: { file: "assets/a.png" }\n',
            **{"assets/a.png": _png() + b"\x00" * (ugc_pack.MAX_ASSET_BYTES + 1)}))
    # 音频魔数
    ugc_pack.validate_package(_pack(
        BASE + 'sounds:\n  s: { file: "assets/s.wav" }\n',
        **{"assets/s.wav": b"RIFF\x00\x00\x00\x00WAVEfmt "}))
    with pytest.raises(ugc_pack.UGCError, match="音频魔数"):
        ugc_pack.validate_package(_pack(
            BASE + 'sounds:\n  s: { file: "assets/s.wav" }\n',
            **{"assets/s.wav": b"not audio"}))


def test_renderer_declaration():
    good = BASE + "renderer: { entry: r.js }\n"
    rep = ugc_pack.validate_package(_pack(good, **{"r.js": "globalThis.Renderer={frame(){}}"}))
    assert rep["meta"]["renderer"]["fallback"] == "declarative"
    bad = [
        (BASE + "renderer: { entry: r.mjs }\n", "类型不支持"),
        (BASE + "renderer: { entry: r.js, protocol: 2 }\n", "protocol"),
        (BASE + "renderer: { entry: r.js, fallback: explode }\n", "fallback"),
        (BASE + "renderer: { entry: missing.js }\n", "不存在于包内"),
        (BASE + "renderer: {}\n", "entry"),
    ]
    for meta, frag in bad:
        with pytest.raises(ugc_pack.UGCError, match=frag):
            ugc_pack.validate_package(_pack(meta, **{"r.js": "x"}))


def test_renderer_static_scan():
    import ugc_static
    assert ugc_static.scan_renderer(
        "globalThis.Renderer = { frame(){} };")["ok"] is True
    for bad in ("fetch('x')", "importScripts('x')", "document.body",
                "window.x", "localStorage.x", "sessionStorage.x",
                "indexedDB.open('x')", "eval('1')", "new Function('1')",
                "new WebSocket('wss://x')", "new XMLHttpRequest()"):
        rep = ugc_static.scan_renderer(bad)
        assert rep["ok"] is False, bad
        assert rep["violations"][0]["line"] == 1


def test_renderer_size_cap(monkeypatch):
    monkeypatch.setattr(ugc_pack, "MAX_RENDERER_BYTES", 16)
    with pytest.raises(ugc_pack.UGCError, match="渲染器过大"):
        ugc_pack.validate_package(_pack(
            BASE + "renderer: { entry: r.js }\n", **{"r.js": "x" * 32}))
