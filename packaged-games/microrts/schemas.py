"""Package-owned JSON Schemas exposed through OpenEnv environment metadata."""

_DRAFT = "https://json-schema.org/draft/2020-12/schema"
_UNIT_TYPES = ["base", "barracks", "worker", "light", "heavy", "ranged"]


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


_BUSY = {
    "anyOf": [
        {"type": "null"},
        {
            "type": "object",
            "required": ["cmd", "dir", "remain"],
            "properties": {
                "cmd": {"type": "integer", "minimum": 0, "maximum": 6},
                "dir": {"type": "integer", "minimum": 0, "maximum": 3},
                "remain": {"type": "integer", "minimum": 0},
                "type": {"type": "string", "enum": _UNIT_TYPES},
            },
            "additionalProperties": False,
        },
    ]
}

_UNIT = {
    "type": "object",
    "required": ["id", "owner", "type", "x", "y", "hp", "carry", "cd",
                 "busy"],
    "properties": {
        "id": {"type": "integer", "minimum": 0},
        "owner": {"type": "integer", "enum": [0, 1]},
        "type": {"type": "string", "enum": _UNIT_TYPES},
        "x": {"type": "integer", "minimum": 0, "maximum": 15},
        "y": {"type": "integer", "minimum": 0, "maximum": 15},
        "hp": {"type": "integer", "minimum": 1, "maximum": 10},
        "carry": {"type": "integer", "minimum": 0, "maximum": 1},
        "cd": {"type": "integer", "minimum": 0},
        "busy": _BUSY,
    },
    "additionalProperties": False,
}

STATE_SCHEMA = {
    "$schema": _DRAFT,
    "type": "object",
    "required": ["grid", "terrain", "units", "bank", "tick", "seed",
                 "time_limit", "done", "winner", "cause", "damage",
                 "opponent", "players", "next_id"],
    "properties": {
        "grid": {"const": [16, 16]},
        "terrain": _fixed_array(
            _fixed_array({"type": "integer", "enum": [0, 1, 2]}, 16), 16),
        "units": {"type": "array", "items": _UNIT, "minItems": 1},
        "bank": _fixed_array({"type": "integer", "minimum": 0}, 2),
        "tick": {"type": "integer", "minimum": 0},
        "seed": {"type": "integer"},
        "time_limit": {"type": "integer", "minimum": 1},
        "done": {"type": "boolean"},
        "winner": {"enum": [None, 0, 1]},
        "cause": {"enum": [None, "eliminated", "time"]},
        "damage": _fixed_array({"type": "integer", "minimum": 0}, 2),
        "opponent": {"type": "string",
                     "enum": ["worker_rush", "light_rush", "ranged_rush",
                              "external"]},
        "players": {"const": 2},
        "next_id": {"type": "integer", "minimum": 0},
        "reward": {"type": "number"},
        "board": _fixed_array(
            _fixed_array({"type": "string",
                          "enum": ["empty", "wall", "mine"]}, 16), 16),
    },
    "additionalProperties": True,
}

_COMMAND = {
    "type": "array",
    "prefixItems": [
        {"type": "integer", "minimum": 0,
         "description": "Unit id"},
        {"type": "integer", "minimum": 0, "maximum": 6,
         "description": "Command code"},
        {"type": "integer", "minimum": 0, "maximum": 3,
         "description": "Direction: north/east/south/west"},
        {"enum": [None, *_UNIT_TYPES],
         "description": "Build or produce type"},
    ],
    "items": False,
    "minItems": 2,
    "maxItems": 4,
}
_COMMANDS = {"type": "array", "items": _COMMAND}

ACTION_SCHEMA = {
    "$schema": _DRAFT,
    "description": ("Built-in-opponent mode accepts one command list; "
                    "external/PvP mode accepts command lists for p0 and p1"),
    "oneOf": [
        _COMMANDS,
        {
            "type": "object",
            "required": ["p0", "p1"],
            "properties": {"p0": _COMMANDS, "p1": _COMMANDS},
            "additionalProperties": False,
        },
    ],
}

ENV_SCHEMAS = {
    "state": STATE_SCHEMA,
    "action": ACTION_SCHEMA,
    "observations": {"grid": _tensor([6, 16, 16])},
}
