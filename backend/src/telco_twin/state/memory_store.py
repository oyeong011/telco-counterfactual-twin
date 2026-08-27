"""Bounded append-only process-memory store with catalog-owned slot leases."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum, unique
from typing import TYPE_CHECKING, assert_never, final

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
from telco_twin.state.store_models import (
    AppendEventRequest,
    EventAppendAccepted,
    EventAppendDenied,
    EventAppendResult,
    SessionAccess,
    SessionAccessCode,
    SessionAccessDenied,
    SessionAccessGranted,
    SessionAccessResult,
    SessionCreate,
    SessionCreated,
    SessionCreateDenied,
    SessionCreateResult,
    SessionSnapshot,
)

if TYPE_CHECKING:
    from telco_twin.domain._contract import ContractId, Sha256Hex, UtcTimestamp


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
    """Mutable bounded session state serialized by its sole AnyIO lock."""

    __slots__ = (
        "created_at",
        "events",
        "expires_at",
        "idempotency",
        "lease_count",
        "lock",
        "prune_requested",
        "session_id",
    )

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
        self.lease_count = 0
        self.prune_requested = False
        self.lock = anyio.Lock()


@unique
class _LeaseStatus(StrEnum):
    ACTIVE = "active"
    EXPIRED = "expired"
    MISSING = "missing"


@dataclass(frozen=True, slots=True)
class _LeaseResult:
    status: _LeaseStatus
    slot: _SessionSlot | None


class DemoSessionStore:
    """Non-durable C1 store bounded by fixed session/event ceilings."""

    _codec: DemoTokenCodec
    _catalog_lock: anyio.Lock
    _sessions: dict[ContractId, _SessionSlot]
    _observed_at: datetime | None

    def __init__(self, *, signing_key: DemoTokenKey, startup_epoch: ContractId) -> None:
        """Bind bounded process state to one secret and startup epoch."""
        self._codec = DemoTokenCodec(signing_key, startup_epoch)
        self._catalog_lock = anyio.Lock()
        self._sessions = {}
        self._observed_at = None

    def _observe(self, now: datetime) -> None:
        if self._observed_at is None or now > self._observed_at:
            self._observed_at = now

    def _expired(self, slot: _SessionSlot) -> bool:
        return self._observed_at is not None and self._observed_at >= datetime.fromisoformat(
            slot.expires_at
        )

    def _prune_expired(self) -> None:
        for session_id, slot in tuple(sorted(self._sessions.items())):
            if not self._expired(slot):
                continue
            if slot.lease_count > 0:
                slot.prune_requested = True
            else:
                del self._sessions[session_id]

    async def _lease_slot(
        self,
        session_id: ContractId,
        now: datetime | None,
    ) -> _LeaseResult:
        async with self._catalog_lock:
            if now is not None:
                self._observe(now)
            self._prune_expired()
            slot = self._sessions.get(session_id)
            if slot is None:
                return _LeaseResult(_LeaseStatus.MISSING, None)
            if slot.prune_requested or self._expired(slot):
                return _LeaseResult(_LeaseStatus.EXPIRED, None)
            slot.lease_count += 1
            return _LeaseResult(_LeaseStatus.ACTIVE, slot)

    async def _lease_status(
        self,
        session_id: ContractId,
        slot: _SessionSlot,
    ) -> _LeaseStatus:
        async with self._catalog_lock:
            if self._sessions.get(session_id) is not slot:
                return _LeaseStatus.MISSING
            if slot.prune_requested or self._expired(slot):
                return _LeaseStatus.EXPIRED
            return _LeaseStatus.ACTIVE

    async def _release_slot(self, session_id: ContractId, slot: _SessionSlot) -> None:
        with anyio.CancelScope(shield=True):
            async with self._catalog_lock:
                slot.lease_count -= 1
                if (
                    slot.lease_count == 0
                    and (slot.prune_requested or self._expired(slot))
                    and self._sessions.get(session_id) is slot
                ):
                    del self._sessions[session_id]

    async def create_session(self, request: SessionCreate) -> SessionCreateResult:
        """Create a live session or fail closed at exact capacity."""
        token, claims = self._codec.issue(
            DemoTokenIssue(session_id=request.session_id, now=request.now, nonce=request.nonce)
        )
        async with self._catalog_lock:
            self._observe(request.now)
            self._prune_expired()
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
        """Append under a cancellation-safe lease or replay the same-body result."""
        lease = await self._lease_slot(request.session_id, None)
        if lease.slot is None:
            return EventAppendDenied(SessionAccessCode.NOT_FOUND)
        try:
            async with lease.slot.lock:
                status = await self._lease_status(request.session_id, lease.slot)
                if status is not _LeaseStatus.ACTIVE:
                    return EventAppendDenied(SessionAccessCode.NOT_FOUND)
                prior = lease.slot.idempotency.get(request.idempotency_key)
                if prior is not None:
                    if prior.body_hash != request.body_hash:
                        return EventAppendDenied(SessionAccessCode.IDEMPOTENCY_CONFLICT)
                    return EventAppendAccepted(event=prior.result.event, replayed=True)
                if len(lease.slot.events) >= MAX_EVENTS_PER_SESSION:
                    return EventAppendDenied(SessionAccessCode.EVENT_CAPACITY)
                frozen = snapshot_event(request.event)
                accepted = EventAppendAccepted(event=frozen, replayed=False)
                lease.slot.events.append(frozen)
                lease.slot.idempotency[request.idempotency_key] = _IdempotencyRecord(
                    body_hash=request.body_hash,
                    result=accepted,
                )
                return accepted
        finally:
            await self._release_slot(request.session_id, lease.slot)

    async def access(self, request: SessionAccess) -> SessionAccessResult:
        """Resolve token semantics and snapshot state under a leased slot."""
        token_result = _TokenAccessResult(result=self._codec.validate(request.token, request.now))
        match token_result.result:
            case DemoTokenRejected() as rejected:
                return _token_denial(rejected)
            case DemoTokenValid(claims=claims):
                lease = await self._lease_slot(claims.session_id, request.now)
            case _:
                assert_never(token_result.result)
        if lease.slot is None:
            match lease.status:
                case _LeaseStatus.EXPIRED:
                    return SessionAccessDenied(SessionAccessCode.EXPIRED, 401)
                case _LeaseStatus.MISSING:
                    return SessionAccessDenied(SessionAccessCode.NOT_FOUND, 404)
                case _LeaseStatus.ACTIVE:
                    return SessionAccessDenied(SessionAccessCode.NOT_FOUND, 404)
                case _:
                    assert_never(lease.status)
        try:
            async with lease.slot.lock:
                lease_status = await self._lease_status(claims.session_id, lease.slot)
                if lease_status is not _LeaseStatus.ACTIVE:
                    return SessionAccessDenied(SessionAccessCode.EXPIRED, 401)
                return SessionAccessGranted(
                    SessionSnapshot(
                        session_id=lease.slot.session_id,
                        startup_epoch=claims.startup_epoch,
                        created_at=lease.slot.created_at,
                        expires_at=lease.slot.expires_at,
                        events=tuple(lease.slot.events),
                    )
                )
        finally:
            await self._release_slot(claims.session_id, lease.slot)

    async def live_session_count(self, now: datetime) -> int:
        """Return retained live/leased count after deterministic pruning."""
        async with self._catalog_lock:
            self._observe(now)
            self._prune_expired()
            return len(self._sessions)
