"""Layering (docs/design/19 §3): dependencies only point down.

    edge  HTTP adapters + composition root: may import any layer
    L3    business: accounts, social, growth, boards, UGC workflow
    L2    match domain: match_engine, matches, matchmaking, models, events
    L1    server runtime: sandbox, registry, package pipeline, inference
    L0    gamekernel: stdlib + numpy only

Every backend module must be listed, so a new file has to pick its layer.
Imports anywhere in a module count, including ones inside functions.
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

LAYERS = {
    "edge": {"main", "openenv_native", "platform_api", "game_routes", "api_limits",
             "api_schemas", "admin_routes", "auth_routes", "matches_routes",
             "model_routes", "social_routes", "stats_routes", "ugc_routes",
             "match_api", "migrate_legacy_matches"},
    "L3": {"auth", "social", "growth", "admin", "scores", "ugc", "ugc_assets"},
    "L2": {"events", "matches", "matchmaking", "models", "match_engine"},
    "L1": {"registry", "ugc_runner", "ugc_worker", "ugc_sandbox", "ugc_proxy",
           "ugc_pack", "package_pipeline", "inference"},
}
RANK = {"L1": 1, "L2": 2, "L3": 3, "edge": 4}
LAYER_OF = {mod: layer for layer, mods in LAYERS.items() for mod in mods}


def _imports(path: Path) -> set[str]:
    out = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            out.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            out.add(node.module.split(".")[0])
    return out


def test_every_backend_module_has_a_layer():
    modules = {p.stem for p in (ROOT / "backend").glob("*.py")}
    assert modules - set(LAYER_OF) == set(), "classify new modules in LAYERS"
    assert set(LAYER_OF) - modules == set(), "remove deleted modules from LAYERS"


def test_backend_dependencies_point_down():
    violations = []
    for path in sorted((ROOT / "backend").glob("*.py")):
        mine = LAYER_OF[path.stem]
        for dep in _imports(path):
            theirs = LAYER_OF.get(dep)
            if theirs is None or dep == path.stem:
                continue  # third-party, stdlib or gamekernel (L0, below everything)
            if RANK[theirs] > RANK[mine]:
                violations.append(f"{path.stem} ({mine}) imports {dep} ({theirs})")
    assert violations == []


def test_kernel_depends_only_on_stdlib_and_numpy():
    allowed = set(sys.stdlib_module_names) | {"numpy", "__future__"}
    violations = []
    for path in sorted((ROOT / "sdk" / "gamekernel").glob("*.py")):
        for dep in _imports(path):
            if dep not in allowed:
                violations.append(f"gamekernel/{path.name} imports {dep}")
    assert violations == []


def test_kernel_has_no_function_level_imports():
    """The sandbox worker imports the kernel before confinement; anything the
    kernel imported later could no longer be read."""
    lazy = []
    for path in sorted((ROOT / "sdk" / "gamekernel").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for fn in ast.walk(tree):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                lazy += [f"gamekernel/{path.name}:{n.lineno}" for n in ast.walk(fn)
                         if isinstance(n, (ast.Import, ast.ImportFrom))]
    assert lazy == []
