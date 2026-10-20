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


_COORDINATE = {
    "type": "array",
    "prefixItems": [
        {"type": "integer", "minimum": 0, "maximum": 19},
        {"type": "integer", "minimum": 0, "maximum": 19},
    ],
    "items": False,
    "minItems": 2,
    "maxItems": 2,
}

STATE_SCHEMA = {
    "$schema": _DRAFT,
    "type": "object",
    "required": ["body", "direction", "food", "score", "tick", "seed",
                 "done", "cause", "grid"],
    "properties": {
        "body": {"type": "array", "items": _COORDINATE,
                 "minItems": 2, "maxItems": 400},
        "direction": {"type": "integer", "enum": [0, 1, 2, 3],
                      "description": "Absolute heading: north/east/south/west"},
        "food": {"anyOf": [_COORDINATE, {"type": "null"}]},
        "score": {"type": "integer", "minimum": 0},
        "tick": {"type": "integer", "minimum": 0},
        "seed": {"type": "integer"},
        "done": {"type": "boolean"},
        "cause": {"enum": [None, "wall", "self", "win"]},
        "grid": {"const": [20, 20]},
        "reward": {"type": "number"},
        "ate": {"type": "boolean"},
        "board": _fixed_array(
            _fixed_array({"type": "string",
                          "enum": ["empty", "body", "head", "food"]}, 20),
            20),
    },
    "additionalProperties": True,
}

ACTION_SCHEMA = {
    "$schema": _DRAFT,
    "type": "integer",
    "enum": [0, 1, 2],
    "description": "Relative turn: 0=left, 1=straight, 2=right",
}

ENV_SCHEMAS = {
    "state": STATE_SCHEMA,
    "action": ACTION_SCHEMA,
    "observations": {
        "grid": _tensor([3, 22, 22]),
        "rotwin": _tensor([1334]),
    },
}
