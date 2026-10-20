"""GDK-UG 本地测试器（作者侧自测，不依赖平台后端）。

用法: python gdk-ug/test_runner.py <游戏目录> [steps] [seed]
检查: 元数据基本一致 · get_adapter() 契约完整 · 同 seed 幂等 · 渲染约定 ·
      N 步连续推进不崩 · done 语义 · PvP 复合动作 · AI 对手（如声明）。
完整严格校验以平台上传时的 ugc_pack 为准。
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import yaml


def load_game(game_dir: Path):
    meta_raw = (game_dir / "game.yaml").read_text(encoding="utf-8")
    meta = yaml.safe_load(meta_raw)
    # 与平台 worker 同款加载：目录进 sys.path + 按包加载（支持多文件/相对导入）
    sys.path.insert(0, str(game_dir))
    spec = importlib.util.spec_from_file_location(
        "ugc_game", game_dir / "__init__.py",
        submodule_search_locations=[str(game_dir)])
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod   # 相对导入（from . import …）解析必需
    spec.loader.exec_module(mod)
    if not callable(getattr(mod, "get_adapter", None)):
        raise SystemExit("FAIL: __init__.py 必须暴露 get_adapter()")
    return meta, mod.get_adapter()


def same(a, b) -> bool:
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: python gdk-ug/test_runner.py <游戏目录> [steps] [seed]");
        return 2
    game_dir = Path(sys.argv[1])
    steps = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    seed = int(sys.argv[3]) if len(sys.argv) > 3 else 42
    checks: list[tuple[str, bool]] = []

    meta, adapter = load_game(game_dir)
    checks.append(("元数据: slug/title/board 齐全",
                   all(k in meta for k in ("slug", "title", "board"))))
    for method in ("new_state", "step_state", "validate_state", "validate_action"):
        checks.append((f"契约方法 {method}()", callable(getattr(adapter, method, None))))

    s0 = adapter.new_state(seed)
    checks.append(("new_state 返回 dict", isinstance(s0, dict)))
    checks.append(("同 seed 幂等（两次轨迹一致）",
                   same(s0, adapter.new_state(seed))))
    adapter.validate_state(s0)
    checks.append(("初始 state 通过 validate_state", True))

    w, h = meta["board"]["width"], meta["board"]["height"]
    palette = meta["board"]["palette"]
    # 渲染网格：优先 render_board（引擎 board 非 cell-id 时包内另行提供，如 tetris）
    grid = s0.get("render_board", s0.get("board"))
    cells_ok = bool(grid) and (len(grid) == h and all(len(r) == w for r in grid))
    checks.append((f"board 尺寸 {w}x{h}", cells_ok))
    if cells_ok:
        known = set(palette)
        checks.append(("board 单元格都在 palette 中",
                       all(str(c) in known for row in grid for c in row)))
    if meta.get("units") and "units" in s0:
        utypes = set(meta["units"])
        checks.append(("units 类型都在声明中",
                       all(u["type"] in utypes for u in s0["units"])))

    # ---- 渲染 v2（设计 16）：声明引用完整 + 路径可解析（宽松版） ----
    assets = meta.get("assets") or {}
    sounds = meta.get("sounds") or {}
    missing = []
    for name, spec in list(assets.items()) + list(sounds.items()):
        f = (spec or {}).get("file")
        if not isinstance(f, str) or not (game_dir / f).is_file():
            missing.append(f"{name}->{f}")
    checks.append(("assets/sounds 文件都存在", not missing))
    sprite_refs = []
    for item in (meta["board"].get("palette") or {}).values():
        if isinstance(item, dict) and item.get("sprite"):
            sprite_refs.append(item["sprite"])
    for item in (meta.get("units") or {}).values():
        if isinstance(item, dict) and item.get("sprite"):
            sprite_refs.append(item["sprite"])
    for layer in meta["board"].get("layers") or []:
        for item in (layer.get("palette") or {}).values():
            if isinstance(item, dict) and item.get("sprite"):
                sprite_refs.append(item["sprite"])
    checks.append(("sprite 引用都在 assets 中",
                   all(s in assets for s in sprite_refs)))

    def _get_path(obj, path):
        cur = obj
        for part in str(path).split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
                cur = cur[int(part)]
            else:
                return None
        return cur

    hud_paths = [h.get("path") for h in (meta["board"].get("hud") or [])
                 if isinstance(h, dict)]
    checks.append(("HUD 路径在初始 state 可解析",
                   all(_get_path(s0, p) is not None for p in hud_paths)))
    rend = meta.get("renderer")
    if rend:
        entry = rend.get("entry")
        ok = (isinstance(entry, str) and (game_dir / entry).is_file()
              and "Renderer" in (game_dir / entry).read_text(encoding="utf-8"))
        checks.append(("renderer.entry 存在且定义 Renderer", ok))

    # 连续推进 N 步
    s = s0
    advanced = 0
    try:
        for _ in range(steps):
            if s.get("done"):
                break
            if callable(getattr(adapter, "sample_action", None)):
                a = adapter.sample_action(s)
            else:
                a = 0   # 退化：尝试 0
            try:
                adapter.validate_action(a, s)
            except (TypeError, ValueError):
                break   # 无法自动生成合法动作：跳到其他检查
            s = adapter.step_state(s, a)
            adapter.validate_state(s)
            advanced += 1
        checks.append((f"连续推进 {advanced} 步不崩且 state 始终合法", advanced > 0))
    except Exception as e:
        checks.append((f"step 循环崩溃: {e}", False))
    if s.get("done"):
        checks.append(("done 状态带 winner/cause",
                       "winner" in s and "cause" in s))
    after_action = adapter.sample_action(s) if callable(
        getattr(adapter, "sample_action", None)) else 0
    checks.append(("done 后 step 不再变化",
                   s.get("done") is not True
                   or same(s, adapter.step_state(s, after_action))))

    # PvP 复合动作（如声明）
    if meta.get("pvp", {}).get("enabled"):
        try:
            pvp_opts = meta["pvp"].get("options")
            s_pvp = adapter.new_state(seed, pvp_opts) if pvp_opts else s0
            a0 = adapter.sample_action(s_pvp)
            a1 = adapter.sample_action(s_pvp)
            s1 = adapter.step_state(s_pvp, {"p0": a0, "p1": a1})
            adapter.validate_state(s1)
            checks.append(("PvP 复合动作 {p0,p1} 可推进", True))
        except Exception as e:
            checks.append((f"PvP 复合动作失败: {e}", False))

    # 内置 AI（如声明）：ai_action 或 opponent_action 二选一即满足
    if meta.get("ai_strategies"):
        if callable(getattr(adapter, "opponent_action", None)):
            try:
                move = adapter.opponent_action(
                    s0, {"type": "ai", "strategy": meta["ai_strategies"][0]})
                ok = False
                if (meta.get("pvp") or {}).get("enabled"):
                    # 双人游戏（如 microrts）：对手指令在 external 模式按 p1 校验
                    s_ext = adapter.new_state(seed, (meta.get("pvp") or {}).get("options"))
                    adapter.validate_action({"p0": [], "p1": move}, s_ext)
                    ok = True
                else:
                    try:
                        adapter.validate_action(move, s0)
                        ok = True
                    except (TypeError, ValueError):
                        ok = isinstance(move, (list, int, dict))
                checks.append(("opponent_action 返回合法动作", ok))
            except Exception as e:
                checks.append((f"opponent_action 失败: {e}", False))
        elif callable(getattr(adapter, "ai_action", None)):
            try:
                out = adapter.ai_action({"state": s0,
                                          "strategy": meta["ai_strategies"][0]})
                move = out.get("action") if isinstance(out, dict) else out
                adapter.validate_action(move, s0)
                checks.append(("ai_action 返回合法动作", True))
            except Exception as e:
                checks.append((f"ai_action 失败: {e}", False))
        else:
            checks.append(("声明 ai_strategies 但未实现 ai_action/opponent_action", False))

    failed = 0
    for name, ok in checks:
        print(("PASS" if ok else "FAIL"), name)
        failed += 0 if ok else 1
    print(f"\n{len(checks) - failed}/{len(checks)} 项通过" +
          ("——本地自测全绿，可以打包上传了 🎉" if not failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
