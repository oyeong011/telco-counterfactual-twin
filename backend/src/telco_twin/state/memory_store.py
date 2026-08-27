"""Bounded append-only process-memory demo session store."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum, unique
from typing import TYPE_CHECKING, Literal, assert_never, final, override

import anyio

from telco_twin.domain._contract import StrictContract
from telco_twin.simulator.frozen_event import FrozenEvent, snapshot_event
from telco_twin.state.demo_token import (
    DemoTokenCodec,
    DemoTokenFailureCode,
    DemoTokenIssue,
    DemoTokenKey,
    DemoTokenRejected,
    DemoTokenResult,
    DemoTokenValid,
)
from telco_twin.state.limits import MAX_EVENTS_PER_SESSION, MAX_LIVE_SESSIONS

if TYPE_CHECKING:
    from telco_twin.domain._contract import ContractId, Sha256Hex, UtcTimestamp
    from telco_twin.domain.event import Event


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
    """One idempotent append request with an independently computed body hash."""

    session_id: ContractId
    idempotency_key: ContractId
    body_hash: Sha256Hex
    event: Event


@dataclass(frozen=True, slots=True)
class EventAppendAccepted:
    """Stored immutable event or same-body replay of its original result."""

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
    """Downloadable live-session evidence with no token or signing key."""

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


class _TokenAccessResult(StrictContract):
    result: DemoTokenResult


class _FailureSelection(StrictContract):
    code: DemoTokenFailureCode


def _token_denial(rejected: DemoTokenRejected) -> SessionAccessDenied:
    selection = _FailureSelection(code=rejected.code)
    match selection.code:
        case DemoTokenFailureCode.INVALID:
            return SessionAccessDenied(SessionAccessCode.INVALID, 401)
        case DemoTokenFailureCode.EXPIRED:
            return SessionAccessDenied(SessionAccessCode.EXPIRED, 401)
        case DemoTokenFailureCode.SESSION_LOST:
            return SessionAccessDenied(SessionAccessCode.LOST, 410)
        case _:
            assert_never(selection.code)


@dataclass(frozen=True, slots=True)
class _IdempotencyRecord:
    body_hash: Sha256Hex
    result: EventAppendAccepted


@final
class _SessionSlot:
    """Intentionally mutable bounded state serialized by its sole AnyIO lock."""

    __slots__ = ("created_at", "events", "expires_at", "idempotency", "lock", "session_id")

    def __init__(
        self,
        session_id: ContractId,
        created_at: UtcTimestamp,
        expires_at: UtcTimestamp,
    ) -> None:
        self.session_id = session_id
        self.created_at = created_at
        self.expires_at = expires_at
        self.events: list[FrozenEvent] = []
        self.idempotency: dict[ContractId, _IdempotencyRecord] = {}
        self.lock = anyio.Lock()


@final
class DemoSessionStore:
    """Non-durable C1 store bounded by fixed session/event ceilings."""

    def __init__(self, *, signing_key: DemoTokenKey, startup_epoch: ContractId) -> None:
        """Bind bounded process state to one secret and startup epoch."""
        self._codec = DemoTokenCodec(signing_key, startup_epoch)
        self._catalog_lock = anyio.Lock()
        self._sessions: dict[ContractId, _SessionSlot] = {}

    def _prune_expired(self, now: datetime) -> None:
        expired = tuple(
            session_id
            for session_id, slot in sorted(self._sessions.items())
            if now >= datetime.fromisoformat(slot.expires_at)
        )
        for session_id in expired:
            del self._sessions[session_id]

    async def create_session(self, request: SessionCreate) -> SessionCreateResult:
        """Create a live session or fail closed at exact capacity."""
        token, claims = self._codec.issue(
            DemoTokenIssue(session_id=request.session_id, now=request.now, nonce=request.nonce)
        )
        async with self._catalog_lock:
            self._prune_expired(request.now)
            if request.session_id in self._sessions:
                return SessionCreateDenied(SessionAccessCode.SESSION_EXISTS)
            if len(self._sessions) >= MAX_LIVE_SESSIONS:
                return SessionCreateDenied(SessionAccessCode.SESSION_CAPACITY)
            self._sessions[request.session_id] = _SessionSlot(
                request.session_id,
                claims.issued_at,
                claims.expires_at,
            )
        return SessionCreated(
            session_id=request.session_id,
            token=token,
            expires_at=claims.expires_at,
            startup_epoch=claims.startup_epoch,
        )

    async def append_event(self, request: AppendEventRequest) -> EventAppendResult:
        """Append once per session/key or replay the exact same-body result."""
        async with self._catalog_lock:
            slot = self._sessions.get(request.session_id)
        if slot is None:
            return EventAppendDenied(SessionAccessCode.NOT_FOUND)
        async with slot.lock:
            prior = slot.idempotency.get(request.idempotency_key)
            if prior is not None:
                if prior.body_hash != request.body_hash:
                    return EventAppendDenied(SessionAccessCode.IDEMPOTENCY_CONFLICT)
                return EventAppendAccepted(event=prior.result.event, replayed=True)
            if len(slot.events) >= MAX_EVENTS_PER_SESSION:
                return EventAppendDenied(SessionAccessCode.EVENT_CAPACITY)
            frozen = snapshot_event(request.event)
            accepted = EventAppendAccepted(event=frozen, replayed=False)
            slot.events.append(frozen)
            slot.idempotency[request.idempotency_key] = _IdempotencyRecord(
                body_hash=request.body_hash,
                result=accepted,
            )
            return accepted

    async def access(self, request: SessionAccess) -> SessionAccessResult:
        """Resolve cryptographic, restart, expiry, and live-state semantics."""
        token_result = _TokenAccessResult(result=self._codec.validate(request.token, request.now))
        match token_result.result:
            case DemoTokenRejected() as rejected:
                return _token_denial(rejected)
            case DemoTokenValid(claims=claims):
                async with self._catalog_lock:
                    slot = self._sessions.get(claims.session_id)
                if slot is None:
                    return SessionAccessDenied(SessionAccessCode.NOT_FOUND, 404)
                async with slot.lock:
                    return SessionAccessGranted(
                        SessionSnapshot(
                            session_id=slot.session_id,
                            startup_epoch=claims.startup_epoch,
                            created_at=slot.created_at,
                            expires_at=slot.expires_at,
                            events=tuple(slot.events),
                        )
                    )
            case _:
                assert_never(token_result.result)

    async def live_session_count(self, now: datetime) -> int:
        """Return the live count after deterministic expiry pruning."""
        async with self._catalog_lock:
            self._prune_expired(now)
            return len(self._sessions)

    @override
    def __repr__(self) -> str:
        return f"DemoSessionStore(startup_epoch={self._codec.startup_epoch!r})"
