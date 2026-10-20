"""Load packaged-games modules the way the sandbox worker does (13 G3):
directory on sys.path + package-style load, so multi-file packages and
relative imports work exactly like in production."""
import importlib
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_game_package(slug: str):
    """Load packaged-games/{slug}/__init__.py as package 'seed_'+slug;
    return the module (cached per slug)."""
    name = "seed_" + slug
    if name in sys.modules:
        return sys.modules[name]
    game_dir = ROOT / "packaged-games" / slug
    sys.path.insert(0, str(game_dir))
    spec = importlib.util.spec_from_file_location(
        name, game_dir / "__init__.py",
        submodule_search_locations=[str(game_dir)])
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def load_submodule(slug: str, sub: str):
    """Load packaged-games/{slug}/{sub}.py as seed_{slug}.{sub}; return it."""
    load_game_package(slug)
    return importlib.import_module("seed_" + slug + "." + sub)
