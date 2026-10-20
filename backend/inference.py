"""ONNX inference — game-agnostic runner (12 §4.4 / 13 G3).

The platform knows NOTHING about individual games here. A game's model face
comes entirely from its package declaration (meta.contract):

    contract: {in_shape, out_shape, protocol: simple|composite, obs_mode?}

- simple:    obs(state, obs_mode) -> model -> argmax  (obs reshaped to in_shape)
- composite: model_inputs(state, owner) per-query inputs -> model each ->
             model_decode(outputs, state, owner) in the game's sandbox
"""
from __future__ import annotations

import numpy as np
import onnxruntime as ort


class ModelError(Exception):
    pass


def _contract_for(game: str, adapter=None) -> dict | None:
    """The registered adapter's meta.contract, normalized; None if absent."""
    from registry import GAMES
    adapter = adapter or GAMES.get(game)
    if adapter is None:
        return None
    meta = getattr(adapter, "meta", None) or {}
    contract = meta.get("contract")
    if not isinstance(contract, dict):
        return None
    in_shape = tuple(contract.get("in_shape") or ())
    out_shape = tuple(contract.get("out_shape") or ())
    if not in_shape or not out_shape:
        return None
    return {"name": f"game.{game}", "input": in_shape, "output": out_shape,
            "protocol": contract.get("protocol", "simple"),
            "obs_mode": contract.get("obs_mode")}


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
    if c["protocol"] == "composite":
        inputs = adapter.model_inputs(state, owner)
        xs = [np.asarray(x, dtype=np.float32).reshape(c["input"]) for x in inputs]
        # 输出转纯 list 再过沙箱 IPC（ndarray 不可 JSON 序列化）
        outs = [np.asarray(_run(sess, x), dtype=np.float32).ravel().tolist()
                for x in xs]
        return adapter.model_decode(outs, state, owner)
    # simple：obs → 模型 → argmax
    mode = c.get("obs_mode")
    if not mode:
        modes = adapter.info().get("obs_modes") or []
        mode = modes[0] if modes else None
    obs = adapter.obs(state, mode)
    if obs is None:
        raise ModelError(f"game {game!r} 未实现 obs，无法用于模型托管")
    x = np.asarray(obs, dtype=np.float32).reshape(c["input"])
    q = _run(sess, x)[0]
    return int(np.argmax(q))
