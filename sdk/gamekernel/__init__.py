"""gamekernel — the rules that make a game package run (docs/design/19, L0).

Pure Python + numpy: no web framework, database, account or network code.
The server's sandbox worker, its OpenEnv sessions, match and evaluation
flows, the SDK's local training and the GDK test runner all import this one
copy, so a game behaves the same everywhere it runs (D3).

Every dependency is imported at module level. The sandbox worker imports the
kernel before it confines the filesystem, after which the kernel's own files
are no longer readable.
"""
__version__ = "1.0.0"

from . import calls, episode, loader, manifest, models, scan  # noqa: F401
