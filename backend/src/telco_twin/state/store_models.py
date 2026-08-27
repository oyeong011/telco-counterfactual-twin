"""Typed public results and requests for the bounded demo store."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum, unique
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from datetime import datetime

    from telco_twin.domain._contract import ContractId, Sha256Hex, UtcTimestamp
    from telco_twin.domain.event import Event
    from telco_twin.simulator.frozen_event import FrozenEvent


@unique
class SessionAccessCode(StrEnum):
    """Stable domain results for later HTTP mapping."""

    INVALID = "demo_token_invalid"
    EXPIRED = "demo_token_expired"
    LOST = "demo_session_lost"
    NOT_FOUND = "demo_session_not_found"
    SESSION_EXISTS = "demo_session_exists"
    SESSION_CAPACITY = "demo_session_capacity"
    EVENT_CAPACITY = "demo_event_capacity"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"


@dataclass(frozen=True, slots=True)
class SessionCreate:
    """Inputs for one bounded live session."""

    session_id: ContractId
    now: datetime
    nonce: bytes


@dataclass(frozen=True, slots=True)
class SessionCreated:
    """Opaque bootstrap token returned once and never persisted."""

    session_id: ContractId
    token: str
    expires_at: UtcTimestamp
    startup_epoch: ContractId


@dataclass(frozen=True, slots=True)
class SessionCreateDenied:
    """Fail-closed session creation result."""

    code: SessionAccessCode


type SessionCreateResult = SessionCreated | SessionCreateDenied


@dataclass(frozen=True, slots=True)
class AppendEventRequest:
    """One idempotent append with an independently computed body hash."""

    session_id: ContractId
    idempotency_key: ContractId
    body_hash: Sha256Hex
    event: Event


@dataclass(frozen=True, slots=True)
class EventAppendAccepted:
    """Stored immutable event or replay of its original result."""

    event: FrozenEvent
    replayed: bool


@dataclass(frozen=True, slots=True)
class EventAppendDenied:
    """Fail-closed append result."""

    code: SessionAccessCode


type EventAppendResult = EventAppendAccepted | EventAppendDenied


@dataclass(frozen=True, slots=True)
class SessionAccess:
    """Opaque token and caller-supplied assessment instant."""

    token: str
    now: datetime


@dataclass(frozen=True, slots=True)
class SessionSnapshot:
    """Downloadable live evidence with no token or signing key."""

    session_id: ContractId
    startup_epoch: ContractId
    created_at: UtcTimestamp
    expires_at: UtcTimestamp
    events: tuple[FrozenEvent, ...]


@dataclass(frozen=True, slots=True)
class SessionAccessGranted:
    """Authenticated current-epoch live evidence snapshot."""

    snapshot: SessionSnapshot


@dataclass(frozen=True, slots=True)
class SessionAccessDenied:
    """Stable status semantic for a later API adapter."""

    code: SessionAccessCode
    http_status: Literal[401, 404, 410]


type SessionAccessResult = SessionAccessGranted | SessionAccessDenied
