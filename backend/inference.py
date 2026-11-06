"""ONNX inference — the onnxruntime shell around gamekernel.models (19).

The platform knows NOTHING about individual games here. The model protocol
(simple / composite, from the package's meta.contract) lives in the kernel and
is shared with the SDK; this module loads sessions, checks uploaded files
against the contract and runs the protocol against the registered adapter.
"""
from __future__ import annotations

import numpy as np
import onnxruntime as ort
from gamekernel import models as kernel_models


class ModelError(Exception):
    pass


def _contract_for(game: str, adapter=None) -> dict | None:
    """The registered adapter's meta.contract, normalized; None if absent."""
    from registry import GAMES
    adapter = adapter or GAMES.get(game)
    if adapter is None:
        return None
    meta = getattr(adapter, "meta", None) or {}
    return kernel_models.contract_of({**meta, "slug": game})


def supports_models(game: str) -> bool:
    """Whether ONNX models can be uploaded for this game (contract declared)."""
    return _contract_for(game) is not None


def load_model(path: str):
    """Load + validate an ONNX file; raises ModelError with a clear message."""
    try:
        sess = ort.InferenceSession(path, providers=["CPUExecutionProvider"])
    except Exception as e:
        raise ModelError(f"无法加载 ONNX 模型：{e}")
    return sess


def check_contract(path: str, game: str) -> str:
    """Verify the file's I/O shapes match the game's declared contract.
    Returns the matched contract name."""
    sess = load_model(path)
    c = _contract_for(game)
    if c is None:
        raise ModelError(f"game {game!r} 未声明模型契约")
    inp = sess.get_inputs()
    if len(inp) != 1:
        raise ModelError(f"模型必须有 1 个输入，实际 {len(inp)} 个")
    in_shape = tuple(inp[0].shape)
    if in_shape != c["input"]:
        raise ModelError(
            f"输入 shape 不匹配：期望 {c['input']}（{c['name']}），实际 {in_shape}")
    outs = sess.get_outputs()
    if len(outs) != 1:
        raise ModelError(f"模型必须有 1 个输出，实际 {len(outs)} 个")
    if tuple(outs[0].shape) != c["output"]:
        raise ModelError(
            f"输出 shape 不匹配：期望 {c['output']}（{c['name']}），实际 {tuple(outs[0].shape)}")
    return c["name"]


def _run(sess, x: np.ndarray) -> np.ndarray:
    return sess.run(None, {sess.get_inputs()[0].name: x})[0]


def model_action(game: str, sess, state: dict, owner: int = 0, *, adapter=None):
    """Generic model action: the ONLY model protocol the platform knows."""
    from registry import GAMES
    adapter = adapter or GAMES[game]
    c = _contract_for(game, adapter)
    if c is None:
        raise ModelError(f"game {game!r} 未声明模型契约")
    modes = () if c["protocol"] == "composite" or c.get("obs_mode") else \
        tuple(adapter.info().get("obs_modes") or ())
    try:
        return kernel_models.model_action(adapter, c, lambda x: _run(sess, x), state,
                                          owner, obs_modes=modes)
    except ValueError as e:
        if "no observation" in str(e):
            raise ModelError(f"game {game!r} 未实现 obs，无法用于模型托管") from e
        raise
