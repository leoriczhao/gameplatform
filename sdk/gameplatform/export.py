"""Export trained torch networks to a game's ONNX model contract.

Each game package declares ONE I/O contract in its game.yaml
(``contract: {in_shape, out_shape, protocol, obs_mode?}``); the server
validates uploaded files against it (backend/inference.py). The exporter reads
the same declaration from the package, so it works for every game, UGC
included, and always matches the version you trained on:

    import torch
    from gameplatform import LocalVecEnv
    from gameplatform.export import export_onnx

    envs = LocalVecEnv(game="snake", n=64, obs_mode="rotwin", base_url=URL)
    ...                                     # train net on envs
    export_onnx(net, game=envs.runtime, path="my_snake_dqn.onnx")

``game`` may also be a slug (the package is fetched from ``base_url``, or
reused from the local cache when ``version`` is given). The export verifies the
I/O shapes exactly like the server does, so a file that passes here will pass
the upload check.
"""
from __future__ import annotations

import os
from pathlib import Path

from .local import LocalGame, _load_yaml, _read_manifest, contract_of, fetch_package
from .remote import DEFAULT_BASE_URL


def _contract(game, base_url: str, version: str | None) -> dict:
    """Read the contract without importing (running) any package code."""
    if isinstance(game, LocalGame):
        meta = game.meta
    elif isinstance(game, Path) or os.sep in game or game.startswith("."):
        manifest = _read_manifest(Path(game))
        meta = manifest["meta"] if manifest else _load_yaml(Path(game) / "game.yaml")
    else:
        # Downloading is not executing: no trust_remote_code needed for metadata.
        meta = _read_manifest(fetch_package(game, version, base_url=base_url,
                                            trust_remote_code=True))["meta"]
    contract = contract_of(meta)
    if contract is None:
        raise ValueError(f"game {meta['slug']!r} declares no model contract")
    return contract


def export_onnx(net, game, path: str, sample_input=None, verify: bool = True, *,
                base_url: str = DEFAULT_BASE_URL, version: str | None = None) -> str:
    """Trace `net` into an ONNX file matching `game`'s contract.

    - `net`: a torch.nn.Module (callable on a float32 batch of the contract
      input shape, returning a float32 tensor of the contract output shape).
    - `game`: a LocalGame (e.g. ``envs.runtime``), a slug, or a package dir.
    - `sample_input`: optional torch tensor; defaults to a random tensor of
      the contract input shape (fine for fixed-shape policy nets).
    - returns the matched contract name ("game.snake" etc.).
    """
    try:
        import torch
    except ImportError as e:  # pragma: no cover
        raise ImportError("export_onnx needs torch: pip install torch") from e

    spec = _contract(game, base_url, version)
    if sample_input is None:
        sample_input = torch.rand(*spec["input"], dtype=torch.float32)
    else:
        sample_input = sample_input.to(dtype=torch.float32)
        if tuple(sample_input.shape) != tuple(spec["input"]):
            raise ValueError(
                f"sample_input shape {tuple(sample_input.shape)} != contract "
                f"input {spec['input']}")

    net.eval()
    with torch.no_grad():
        torch.onnx.export(
            net, sample_input, path,
            input_names=["x"], output_names=["q"],
            opset_version=13, dynamo=False,
            dynamic_axes=None,  # contracts are fixed-shape
        )
    if verify:
        _verify(path, spec)
    return spec["name"]


def _verify(path: str, spec: dict) -> None:
    """Same shape check as the server's upload validation."""
    try:
        import numpy as np
        import onnxruntime as ort
    except ImportError as e:  # pragma: no cover
        raise ImportError("verification needs numpy + onnxruntime") from e

    sess = ort.InferenceSession(path, providers=["CPUExecutionProvider"])
    ins = sess.get_inputs()
    outs = sess.get_outputs()
    if len(ins) != 1 or tuple(ins[0].shape) != tuple(spec["input"]):
        raise ValueError(
            f"exported input shape mismatch: expected {spec['input']} "
            f"({spec['name']}), got {tuple(ins[0].shape) if ins else '?'}")
    if len(outs) != 1 or tuple(outs[0].shape) != tuple(spec["output"]):
        raise ValueError(
            f"exported output shape mismatch: expected {spec['output']} "
            f"({spec['name']}), got {tuple(outs[0].shape) if outs else '?'}")
    x = np.random.rand(*spec["input"]).astype(np.float32)
    sess.run(None, {ins[0].name: x})
