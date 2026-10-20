"""UGC AST static scan (11 P3, design 10 §5 第二层防线)。

上传时解析全部 .py：
- import 白名单（标准库白名单子集 + numpy；相对导入放行）
- 调用点黑名单：eval/exec/compile/__import__、open 写模式
任何违规 → 上传被拒（报告随版本入库，供审核展示）。
注意：这是审核辅助层，不是完备沙箱；运行时禁能桩（ugc_worker）才是兜底。
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

ALLOWED_IMPORTS = {
    "__future__", "abc", "bisect", "collections", "copy", "dataclasses",
    "enum", "functools", "heapq", "itertools", "json", "math", "re",
    "random", "string", "typing", "numpy",
}
BLOCKED_CALLS = {"eval", "exec", "compile", "__import__"}
WRITE_MODES = set("wax+")


# L3 沙箱渲染器（16 §5.1）：审核辅助层，真正的边界是 opaque-origin Worker。
RENDERER_BLOCKED = [
    (r"\bimportScripts\s*\(", "禁止 importScripts()"),
    (r"\bXMLHttpRequest\b", "禁止网络请求"),
    (r"\bWebSocket\b", "禁止网络请求"),
    (r"\bfetch\s*\(", "禁止网络请求"),
    (r"\blocalStorage\b|\bsessionStorage\b|\bindexedDB\b", "禁止访问存储"),
    (r"\bdocument\b", "禁止访问 DOM"),
    (r"\bwindow\b", "禁止访问 window"),
    (r"\beval\s*\(", "禁止 eval()"),
    (r"\bnew\s+Function\b", "禁止 new Function()"),
]


def scan_renderer(text: str) -> dict:
    """扫描 renderer.js 的明显越界调用。返回 {ok, violations}。"""
    violations: list[dict] = []
    for pattern, detail in RENDERER_BLOCKED:
        m = re.search(pattern, text)
        if m:
            violations.append({
                "file": "renderer.js",
                "line": text.count("\n", 0, m.start()) + 1,
                "kind": "renderer", "detail": detail})
    return {"ok": not violations, "violations": violations}


def scan_dir(game_dir) -> dict:
    """Scan every .py under game_dir. Returns
    {"ok": bool, "violations": [{file, line, kind, detail}]}."""
    violations: list[dict] = []
    for py in sorted(Path(game_dir).rglob("*.py")):
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except SyntaxError as e:
            violations.append({"file": str(py.relative_to(game_dir)),
                                "line": e.lineno or 0, "kind": "syntax",
                                "detail": str(e)})
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    if root not in ALLOWED_IMPORTS:
                        violations.append({
                            "file": str(py.relative_to(game_dir)),
                            "line": node.lineno, "kind": "import",
                            "detail": f"不允许的 import：{alias.name}"})
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                root = (node.module or "").split(".")[0]
                if root not in ALLOWED_IMPORTS:
                    violations.append({
                        "file": str(py.relative_to(game_dir)),
                        "line": node.lineno, "kind": "import",
                        "detail": f"不允许的 import：{node.module}"})
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in BLOCKED_CALLS:
                    violations.append({
                        "file": str(py.relative_to(game_dir)),
                        "line": node.lineno, "kind": "call",
                        "detail": f"禁止调用 {node.func.id}()"})
                elif node.func.id == "open" and len(node.args) > 1 \
                        and isinstance(node.args[1], ast.Constant) \
                        and set(str(node.args[1].value)) & WRITE_MODES:
                    violations.append({
                        "file": str(py.relative_to(game_dir)),
                        "line": node.lineno, "kind": "file_write",
                        "detail": "禁止以写模式 open()"})
    return {"ok": not violations, "violations": violations}
