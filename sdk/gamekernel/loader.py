"""Import a game package directory and return its adapter."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


class PackageError(RuntimeError):
    pass


def load_package(game_dir, module_name: str = "ugc_game"):
    """Load ``game_dir/__init__.py`` as a package and call ``get_adapter()``.

    Multi-file packages work: the package directory goes on ``sys.path`` and
    the module is registered under ``module_name``, so both relative imports
    (``from . import env``) and absolute imports of the package's own modules
    resolve. Two packages that use absolute imports of same-named modules
    therefore cannot share one process.
    """
    game_dir = Path(game_dir).resolve()
    if str(game_dir) not in sys.path:
        sys.path.insert(0, str(game_dir))
    spec = importlib.util.spec_from_file_location(
        module_name, game_dir / "__init__.py",
        submodule_search_locations=[str(game_dir)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module  # required for relative imports
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(module_name, None)
        raise
    if not callable(getattr(module, "get_adapter", None)):
        raise PackageError("__init__.py 必须暴露 get_adapter()")
    return module.get_adapter()
