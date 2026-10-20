"""UGC package validator tests (11 P1): zip safety + game.yaml schema."""
import io
import sys
import tempfile
import zipfile
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

import ugc_pack  # noqa: E402

GOOD_META = """slug: my-game
title: 我的游戏
description: 一句话介绍
version: 1.0.0
board:
  width: 8
  height: 8
  palette:
    empty: { glyph: "·", color: "#e4e4e7" }
    wall:  { glyph: "🧱" }
"""


def _zip(files) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            data = content.encode() if isinstance(content, str) else content
            zf.writestr(name, data)
    return buf.getvalue()


def _good_pack(**extra) -> bytes:
    files = {
        "game.yaml": GOOD_META,
        "__init__.py": "def get_adapter():\n    raise NotImplementedError\n",
        "game.py": "# logic\n",
        "README.md": "# 玩法\n",
    }
    files.update(extra)
    return _zip(files)


def _meta(**extra) -> bytes:
    """game.yaml with overridden top-level fields (dict merge via text)"""
    files = {"game.yaml": GOOD_META, "__init__.py": "x=1\n"}
    files.update(extra)
    return _zip(files)


def test_legal_package_passes():
    rep = ugc_pack.validate_package(_good_pack())
    assert len(rep["sha256"]) == 64
    assert rep["size"] > 0
    assert set(rep["files"]) == {"game.yaml", "__init__.py", "game.py", "README.md"}
    m = rep["meta"]
    assert m["slug"] == "my-game" and m["version"] == "1.0.0"
    assert m["board"]["width"] == 8 and m["board"]["height"] == 8
    assert m["board"]["palette"]["empty"] == {"glyph": "·", "color": "#e4e4e7"}


def test_rejects_missing_required_files():
    with pytest.raises(ugc_pack.UGCError, match="__init__"):
        ugc_pack.validate_package(_zip({"game.yaml": GOOD_META}))
    with pytest.raises(ugc_pack.UGCError, match="game.yaml"):
        ugc_pack.validate_package(_zip({"__init__.py": "x=1\n"}))


def test_rejects_binary_extensions():
    for name in ("evil.so", "x.exe", "x.pyd", "x.dll", "x.svg", "x.zip"):
        with pytest.raises(ugc_pack.UGCError, match="不允许的文件类型"):
            ugc_pack.validate_package(_good_pack(**{name: "MZ\x00\x00"}))
    # 图片/音效/渲染器扩展名合法，但必须显式声明（16 §4.1）
    for name in ("x.png", "x.webp", "x.ogg", "x.js"):
        with pytest.raises(ugc_pack.UGCError, match="未声明的资源文件"):
            ugc_pack.validate_package(_good_pack(**{name: "MZ\x00\x00"}))


def test_rejects_path_traversal_and_absolute():
    for name in ("../evil.py", "a/../../evil.py", "/etc/passwd",
                 "C:\\evil.py"):
        with pytest.raises(ugc_pack.UGCError, match="非法路径"):
            ugc_pack.validate_package(_good_pack(**{name: "x=1\n"}))


def test_rejects_symlink_entry():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("game.yaml", GOOD_META)
        zf.writestr("__init__.py", "x=1\n")
        info = zipfile.ZipInfo("link.py")
        info.create_system = 3
        info.external_attr = 0o120777 << 16   # symlink mode bits
        zf.writestr(info, b"")
    with pytest.raises(ugc_pack.UGCError, match="符号链接"):
        ugc_pack.validate_package(buf.getvalue())


def test_rejects_non_utf8(monkeypatch):
    with pytest.raises(ugc_pack.UGCError, match="UTF-8"):
        ugc_pack.validate_package(_good_pack(**{"bad.py": b"\xff\xfe\x00"}))


def test_rejects_oversize_pack_and_file(monkeypatch):
    monkeypatch.setattr(ugc_pack, "MAX_PACK_BYTES", 512)
    with pytest.raises(ugc_pack.UGCError, match="MB"):
        ugc_pack.validate_package(_good_pack(**{"big.py": "#" * 600}))
    # 单文件超限（zip 炸弹手法）：手工把中央目录里 big.py 的未压缩大小
    # 虚报为 200KB，而实际数据很小——总大小检查拦不住，靠逐文件检查
    import struct
    monkeypatch.setattr(ugc_pack, "MAX_PACK_BYTES", 100_000)
    raw = bytearray(_good_pack(**{"big.py": "x=1\n"}))
    idx = raw.rfind(b"big.py")          # 中央目录记录（在 zip 末尾）
    assert idx > 0
    struct.pack_into("<I", raw, idx - 22, 200_000)  # uncompressed size 字段
    with pytest.raises(ugc_pack.UGCError, match="文件过大"):
        ugc_pack.validate_package(bytes(raw))


def test_rejects_too_many_files(monkeypatch):
    monkeypatch.setattr(ugc_pack, "MAX_FILES", 2)
    with pytest.raises(ugc_pack.UGCError, match="文件数"):
        ugc_pack.validate_package(_good_pack(**{"c.py": "1\n", "d.py": "2\n"}))


def test_meta_schema_rejections():
    cases = [
        ({"game.yaml": GOOD_META.replace("slug: my-game", "slug: My_Game")}, "slug"),
        ({"game.yaml": GOOD_META.replace("slug: my-game", "slug: ugc")}, "保留"),
        ({"game.yaml": GOOD_META.replace("version: 1.0.0", "version: v1")}, "version"),
        ({"game.yaml": GOOD_META.replace("title: 我的游戏", "extra: 1\ntitle: 我的游戏")}, "未知字段"),
        ({"game.yaml": GOOD_META.replace("  width: 8", "  width: 0")}, "width"),
        ({"game.yaml": GOOD_META.replace('glyph: "·", color: "#e4e4e7"', 'glyph: "·", color: "red"')}, "#rrggbb"),
    ]
    for files, frag in cases:
        with pytest.raises(ugc_pack.UGCError, match=frag):
            ugc_pack.validate_package(_meta(**files))

    # 与内置游戏冲突（调用方传入注册表名单）
    with pytest.raises(ugc_pack.UGCError, match="占用"):
        ugc_pack.validate_package(
            _meta(**{"game.yaml": GOOD_META.replace("slug: my-game", "slug: snake")}),
            builtin_games={"snake", "tetris", "microrts"})


def test_meta_pvp_and_contract_schema():
    pvp_ok = GOOD_META + """
pvp:
  enabled: true
  action: choice
  choices: ["石头", "剪刀", "布"]
contract:
  in_shape: [1, 64]
  out_shape: [1, 3]
"""
    rep = ugc_pack.validate_package(_meta(**{"game.yaml": pvp_ok}))
    assert rep["meta"]["pvp"] == {"enabled": True, "action": "choice",
                                   "choices": ["石头", "剪刀", "布"]}
    assert rep["meta"]["contract"]["in_shape"] == [1, 64]

    bad = [
        (pvp_ok.replace("action: choice", "action: banana"), "unit 或 choice"),
        (pvp_ok.replace('choices: ["石头", "剪刀", "布"]', ""), "2-16"),
        (pvp_ok.replace("in_shape: [1, 64]", "in_shape: []"), "1-4 维"),
    ]
    for text, frag in bad:
        with pytest.raises(ugc_pack.UGCError, match=frag):
            ugc_pack.validate_package(_meta(**{"game.yaml": text}))


def test_v2_binary_resources_allowed():
    import numpy as np
    buf = io.BytesIO()
    np.savez(buf, w=np.ones((2, 2), dtype=np.float32))
    pack = _good_pack(**{"weights.npz": buf.getvalue(), "data.bin": b"\x00\x01"})
    rep = ugc_pack.validate_package(pack)
    assert "weights.npz" in rep["files"] and "data.bin" in rep["files"]


def test_v2_meta_extensions():
    v2 = GOOD_META + """
contract:
  in_shape: [1, 64]
  out_shape: [1, 3]
  protocol: composite
pvp:
  enabled: true
  action: unit
  options: { opponent: external }
opponents: [greedy, random]
default_opponent: greedy
controls:
  mode: relative-turn
  direction_field: direction
  keys:
    ArrowUp: [3, "上"]
    ArrowDown: [1, "下"]
"""
    rep = ugc_pack.validate_package(_meta(**{"game.yaml": v2}))
    m = rep["meta"]
    assert m["contract"] == {"in_shape": [1, 64], "out_shape": [1, 3],
                              "protocol": "composite"}
    assert m["pvp"]["options"] == {"opponent": "external"}
    assert m["opponents"] == ["greedy", "random"]
    assert m["default_opponent"] == "greedy"
    assert m["controls"]["mode"] == "relative-turn"
    assert m["controls"]["keys"]["ArrowUp"] == [3, "上"]

    bad = [
        (v2.replace("protocol: composite", "protocol: banana"), "simple 或 composite"),
        (v2.replace("default_opponent: greedy", "default_opponent: nope"), "必须在 opponents"),
        (v2.replace("mode: relative-turn", "mode: tilt"), "absolute 或 relative-turn"),
        (v2.replace('ArrowUp: [3, "上"]', "ArrowUp: 3"), "[动作值, 标签]"),
    ]
    for text, frag in bad:
        with pytest.raises(ugc_pack.UGCError, match=frag):
            ugc_pack.validate_package(_meta(**{"game.yaml": text}))

    # contract 缺省 protocol = simple
    rep2 = ugc_pack.validate_package(_meta(**{
        "game.yaml": GOOD_META + """
contract:
  in_shape: [1, 4]
  out_shape: [1, 2]
"""}))
    assert rep2["meta"]["contract"]["protocol"] == "simple"


def test_extract_package_safe():
    with tempfile.TemporaryDirectory() as td:
        dest = Path(td) / "game"
        rep = ugc_pack.extract_package(_good_pack(), dest)
        assert (dest / "game.yaml").exists()
        assert (dest / "game.py").exists()
        assert rep["meta"]["slug"] == "my-game"
        # traversal 包在任何落盘前被拒
        with pytest.raises(ugc_pack.UGCError):
            ugc_pack.extract_package(
                _good_pack(**{"../evil.py": "x=1\n"}), Path(td) / "bad")
        assert not (Path(td) / "evil.py").exists()
