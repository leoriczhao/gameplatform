"""Shared OpenAPI contracts for platform play-session and match APIs.

Environment wire models and schemas are provided by the OpenEnv subapplication.
Game state and actions remain package-owned JSON values in platform APIs.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class SessionKind(str, Enum):
    PVE = "pve"
    PVP = "pvp"


class SessionStatus(str, Enum):
    WAITING = "waiting"
    ACTIVE = "active"
    FINISHED = "finished"
    ABANDONED = "abandoned"
    CANCELLED = "cancelled"


class MatchKind(str, Enum):
    PVE = "pve"
    PVP = "pvp"
    MODEL_VS_MODEL = "model_vs_model"


class MatchStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    FINISHED = "finished"
    FAILED = "failed"


class MatchMode(str, Enum):
    RANKED = "ranked"
    CASUAL = "casual"


class SessionVisibility(str, Enum):
    PUBLIC = "public"
    PRIVATE = "private"


class PlayerSide(str, Enum):
    P0 = "p0"
    P1 = "p1"


class ParticipantSide(str, Enum):
    P0 = "p0"
    P1 = "p1"
    OWNER = "owner"



class SessionPlayer(BaseModel):
    name: str | None
    side: PlayerSide
    submitted: bool | None = None


class SessionView(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    game: str
    kind: SessionKind
    status: SessionStatus
    tick: int = Field(ge=0)
    state: dict[str, Any]
    winner: int | None
    cause: str | None
    opponent: dict[str, Any] | None
    side: PlayerSide
    invite: str | None = None
    mode: MatchMode | None = None
    visibility: SessionVisibility | None = None
    players: list[SessionPlayer] | None = None
    p1_joined: bool | None = None
    created_at: float | None = None
    updated_at: float | None = None
    game_version: str | None = None
    match_id: int | None = None


class CreateSessionResponse(BaseModel):
    session: SessionView
    invite: str | None = None
    side: PlayerSide | None = None


class GetSessionResponse(BaseModel):
    session: SessionView
    side: PlayerSide | None = None


class SessionActionResponse(BaseModel):
    state: dict[str, Any]
    tick: int = Field(ge=0)
    done: bool
    winner: int | None
    cause: str | None
    status: SessionStatus
    reward: float | None = None
    advanced: bool | None = None
    waiting_for: PlayerSide | None = None
    game_version: str | None = None
    match_id: int | None = None


class LeaveSessionResponse(BaseModel):
    status: SessionStatus
    winner: int | None = None


class ActiveSessionsResponse(BaseModel):
    sessions: list[SessionView]


class RoomView(BaseModel):
    id: str
    game: str
    mode: MatchMode
    visibility: SessionVisibility
    invite: str
    host: str
    host_id: int
    created_at: float = Field(description="Unix timestamp in seconds")
    updated_at: float = Field(description="Unix timestamp in seconds")


class RoomsResponse(BaseModel):
    rooms: list[RoomView]


class ReplayMove(BaseModel):
    """One deterministic transition input in replay order."""

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


class SessionReplayResult(BaseModel):
    status: SessionStatus
    winner: int | None
    cause: str | None


class SessionReplay(BaseModel):
    schema_version: Literal[1]
    id: str = Field(description="Session id")
    game: str
    game_version: str | None
    kind: SessionKind
    seed: int | None
    options: dict[str, Any] | None
    players: list[ReplayPlayer]
    opponent: dict[str, Any] | None
    moves: list[ReplayMove]
    result: SessionReplayResult


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

    winner: int | None = None
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


class CreateMatchResponse(BaseModel):
    match_id: int


class MatchesResponse(BaseModel):
    matches: list[MatchRecord]


class MatchDetailResponse(BaseModel):
    match: MatchRecord


class MatchReplay(BaseModel):
    schema_version: Literal[1]
    match_id: int
    game: str
    game_version: str | None
    kind: MatchKind
    players: list[ReplayPlayer]
    models: list[ModelParticipant]
    result: MatchResult
    mode: MatchMode | None
    seed: int | None
    options: dict[str, Any] | None
    moves: list[ReplayMove]
    created_at: float = Field(description="Unix timestamp in seconds")
    finished_at: float = Field(description="Unix timestamp in seconds")


class MatchReplayResponse(BaseModel):
    replay: MatchReplay
