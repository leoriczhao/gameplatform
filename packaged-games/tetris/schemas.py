"""Package-owned JSON Schemas exposed through OpenEnv environment metadata."""

_DRAFT = "https://json-schema.org/draft/2020-12/schema"


def _fixed_array(items: dict, size: int) -> dict:
    return {"type": "array", "items": items,
            "minItems": size, "maxItems": size}


def _tensor(shape: list[int]) -> dict:
    schema = {"type": "number"}
    for size in reversed(shape):
        schema = _fixed_array(schema, size)
    schema.update({"$schema": _DRAFT, "x-shape": shape,
                   "x-dtype": "float32"})
    return schema


_PIECE = {
    "type": "object",
    "required": ["id", "rot", "x", "y"],
    "properties": {
        "id": {"type": "integer", "minimum": 0, "maximum": 6},
        "rot": {"type": "integer", "minimum": 0, "maximum": 3},
        "x": {"type": "integer", "minimum": -4, "maximum": 10},
        "y": {"type": "integer", "minimum": -4, "maximum": 20},
    },
    "additionalProperties": False,
}

STATE_SCHEMA = {
    "$schema": _DRAFT,
    "type": "object",
    "required": ["board", "piece", "next", "bag", "bag_pos", "bag_idx",
                 "score", "lines", "tick", "seed", "done", "cause", "grid"],
    "properties": {
        "board": _fixed_array(
            _fixed_array({"type": "integer", "minimum": 0, "maximum": 7}, 10),
            20),
        "piece": _PIECE,
        "next": {"type": "integer", "minimum": 0, "maximum": 6},
        "bag": {**_fixed_array(
            {"type": "integer", "minimum": 0, "maximum": 6}, 7),
            "uniqueItems": True},
        "bag_pos": {"type": "integer", "minimum": 0, "maximum": 6},
        "bag_idx": {"type": "integer", "minimum": 0},
        "score": {"type": "integer", "minimum": 0},
        "lines": {"type": "integer", "minimum": 0},
        "tick": {"type": "integer", "minimum": 0},
        "seed": {"type": "integer"},
        "done": {"type": "boolean"},
        "cause": {"enum": [None, "lockout"]},
        "grid": {"const": [10, 20]},
        "reward": {"type": "number"},
        "render_board": _fixed_array(
            _fixed_array({"type": "string",
                          "enum": ["0", "1", "2", "3", "4", "5", "6",
                                   "7", "active"]}, 10),
            20),
    },
    "additionalProperties": True,
}

ACTION_SCHEMA = {
    "$schema": _DRAFT,
    "type": "integer",
    "enum": [0, 1, 2, 3],
    "description": "0=left, 1=right, 2=rotate, 3=hard drop",
}

ENV_SCHEMAS = {
    "state": STATE_SCHEMA,
    "action": ACTION_SCHEMA,
    "observations": {"grid": _tensor([2, 20, 10])},
}
