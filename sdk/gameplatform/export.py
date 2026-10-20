"""Export trained torch networks to the platform's ONNX model contracts.

Each game declares ONE standard I/O contract; the server validates uploaded
files against it (see backend/inference.py IO_CONTRACTS):

    snake.q3      in float32 (1,1334)      -> out (1,3)    Q values
    tetris.q4     in float32 (1,2,20,10)   -> out (1,4)    Q values
    microrts.c140 in float32 (1,1546)      -> out (1,140)  cmd x dir x type logits

Usage:

    import torch
    from gameplatform.export import export_onnx

    net = MLP(1334, 3)                      # trained with obs_mode="rotwin"
    export_onnx(net, game="snake", path="my_snake_dqn.onnx")

The export verifies the I/O shapes exactly like the server does, so a file
that passes here will pass the upload check.
"""
from __future__ import annotations

CONTRACTS = {
    "snake":    {"name": "snake.q3",      "input": (1, 1334),      "output": (1, 3)},
    "tetris":   {"name": "tetris.q4",     "input": (1, 2, 20, 10), "output": (1, 4)},
    "microrts": {"name": "microrts.c140", "input": (1, 1546),      "output": (1, 140)},
}


def export_onnx(net, game: str, path: str, sample_input=None,
                verify: bool = True) -> str:
    """Trace `net` into an ONNX file matching `game`'s contract.

    - `net`: a torch.nn.Module (callable on a float32 batch of the contract
      input shape, returning a float32 tensor of the contract output shape).
    - `sample_input`: optional torch tensor; defaults to a random tensor of
      the contract input shape (fine for fixed-shape policy nets).
    - returns the matched contract name ("snake.q3" etc.).
    """
    try:
        import torch
    except ImportError as e:  # pragma: no cover
        raise ImportError("export_onnx needs torch: pip install torch") from e

    spec = CONTRACTS.get(game)
    if spec is None:
        raise ValueError(f"unknown game {game!r}; choose from {sorted(CONTRACTS)}")

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
        _verify(path, game)
    return spec["name"]


def _verify(path: str, game: str) -> None:
    """Same shape check as the server's upload validation."""
    try:
        import numpy as np
        import onnxruntime as ort
    except ImportError as e:  # pragma: no cover
        raise ImportError("verification needs numpy + onnxruntime") from e

    spec = CONTRACTS[game]
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
