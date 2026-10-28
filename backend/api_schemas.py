"""Shared OpenAPI contracts for match history/record APIs.

Environment wire models and schemas are provided by the OpenEnv subapplication.
Game state and actions remain package-owned JSON values in platform APIs.
对局协议只有 v2（docs/design/17）：这里保留历史记录投影（含归档 v1 行）的
Match 契约；v1 play session / 回放模型随 v1 API 在 M4 删除。
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class MatchKind(str, Enum):
    PVE = "pve"
    PVP = "pvp"
    MODEL_VS_MODEL = "model_vs_model"   # 仅归档 v1 行；新对局不再产生


class MatchStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    FINISHED = "finished"
    FAILED = "failed"
    # v2（设计 17）的对局状态；历史记录可能出现 aborted/cancelled。
    WAITING = "waiting"
    ACTIVE = "active"
    ABORTED = "aborted"
    CANCELLED = "cancelled"


class MatchMode(str, Enum):
    RANKED = "ranked"
    CASUAL = "casual"
    PRACTICE = "practice"      # v2：单机练习局


class SessionVisibility(str, Enum):
    PUBLIC = "public"
    PRIVATE = "private"
    UNLISTED = "unlisted"      # v2：凭链接可读、不进大厅


class PlayerSide(str, Enum):
    P0 = "p0"
    P1 = "p1"


class ParticipantSide(str, Enum):
    P0 = "p0"
    P1 = "p1"
    OWNER = "owner"


class ReplayMove(BaseModel):
    """One deterministic transition input in replay order (archived v1 rows)."""

    model_config = ConfigDict(extra="allow")

    tick: int = Field(ge=0, description="Tick before applying this action")
    action: Any = Field(description="Game-specific action for this transition")
    opponent: Any | None = Field(
        default=None,
        description="Actual PvE opponent action, when the server supplied one")


class ReplayPlayer(BaseModel):
    user_id: int | None = None
    name: str | None
    side: ParticipantSide


class ModelParticipant(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: Literal["model", "ai"] | None = None
    side: PlayerSide | None = None
    model_id: int | None = None
    name: str | None = None
    owner_id: int | None = None
    strategy: str | None = None


class StoredReplay(BaseModel):
    schema_version: Literal[1] | None = None
    game_version: str | None = None
    seed: int | None = None
    options: dict[str, Any] | None = None
    moves: list[ReplayMove] = Field(default_factory=list)


class MatchResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    # v1 是 0/1；v2（设计 17）用座位 id "p0"/"p1"，过渡期两种都接受。
    winner: int | str | None = None
    cause: str | None = None
    mode: MatchMode | None = None
    damage: list[int] | None = None
    score: int | float | None = None
    tick: int | None = None
    error: str | None = None


class MatchRecord(BaseModel):
    id: int
    game: str
    kind: MatchKind
    players: list[ReplayPlayer]
    models: list[ModelParticipant]
    status: MatchStatus
    result: MatchResult | None
    replay: StoredReplay | list[ReplayMove] | None
    created_at: float = Field(description="Unix timestamp in seconds")
    finished_at: float | None = Field(
        default=None, description="Unix timestamp in seconds")
    # v2 记录（设计 17）：uid 是对外 id，/m/:id 舞台用；v1 旧记录为 None。
    uid: str | None = None
    mode: MatchMode | None = None
    visibility: SessionVisibility | None = None
    version: str | None = None


class MatchesResponse(BaseModel):
    matches: list[MatchRecord]


class MatchDetailResponse(BaseModel):
    match: MatchRecord
