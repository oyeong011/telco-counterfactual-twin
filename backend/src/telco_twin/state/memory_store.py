"""Authenticated bounded process-memory demo session store."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, assert_never

from telco_twin.state.demo_token import (
    DemoTokenCodec,
    DemoTokenFailureCode,
    DemoTokenIssue,
    DemoTokenKey,
    DemoTokenRejected,
    DemoTokenValid,
)
from telco_twin.state.event_append import append_to_slot
from telco_twin.state.session_catalog import (
    CatalogCreateStatus,
    LeaseResult,
    LeaseStatus,
    SessionCatalog,
    SessionSlot,
)
from telco_twin.state.store_models import (
    AppendEventRequest,
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
from telco_twin.state.trusted_clock import TrustedClock, trusted_now

if TYPE_CHECKING:
    from telco_twin.domain._contract import ContractId

type AccessFailureCode = Literal[
    SessionAccessCode.INVALID,
    SessionAccessCode.EXPIRED,
    SessionAccessCode.LOST,
    SessionAccessCode.NOT_FOUND,
]


def _token_code(code: DemoTokenFailureCode) -> AccessFailureCode:
    match code:
        case DemoTokenFailureCode.INVALID:
            return SessionAccessCode.INVALID
        case DemoTokenFailureCode.EXPIRED:
            return SessionAccessCode.EXPIRED
        case DemoTokenFailureCode.SESSION_LOST:
            return SessionAccessCode.LOST
        case _:  # pragma: no cover - exhaustive enum
            assert_never(code)


def _access_denial(code: AccessFailureCode) -> SessionAccessDenied:
    match code:
        case SessionAccessCode.LOST:
            return SessionAccessDenied(code, 410)
        case SessionAccessCode.NOT_FOUND:
            return SessionAccessDenied(code, 404)
        case SessionAccessCode.INVALID | SessionAccessCode.EXPIRED:
            return SessionAccessDenied(code, 401)
        case _:  # pragma: no cover - exhaustive access union
            assert_never(code)


def _lease_code(lease: LeaseResult) -> AccessFailureCode:
    match lease.status:
        case LeaseStatus.EXPIRED:
            return SessionAccessCode.EXPIRED
        case LeaseStatus.MISSING | LeaseStatus.ACTIVE:
            return SessionAccessCode.NOT_FOUND
        case _:  # pragma: no cover - exhaustive lease enum
            assert_never(lease.status)


class DemoSessionStore:
    """Non-durable store owning token verification, clock, slots, and append."""

    _codec: DemoTokenCodec
    _clock: TrustedClock
    _catalog: SessionCatalog

    def __init__(
        self,
        *,
        signing_key: DemoTokenKey,
        startup_epoch: ContractId,
        clock: TrustedClock,
    ) -> None:
        """Bind process state to one HMAC key, startup epoch, and trusted clock."""
        self._codec = DemoTokenCodec(signing_key, startup_epoch)
        self._clock = clock
        self._catalog = SessionCatalog()

    async def create_session(self, request: SessionCreate) -> SessionCreateResult:
        """Create a live session at trusted time or fail closed at capacity."""
        now = trusted_now(self._clock)
        token, claims = self._codec.issue(
            DemoTokenIssue(session_id=request.session_id, now=now, nonce=request.nonce)
        )
        slot = SessionSlot(request.session_id, claims.issued_at, claims.expires_at)
        status = await self._catalog.create(slot, now)
        match status:
            case CatalogCreateStatus.EXISTS:
                return SessionCreateDenied(SessionAccessCode.SESSION_EXISTS)
            case CatalogCreateStatus.CAPACITY:
                return SessionCreateDenied(SessionAccessCode.SESSION_CAPACITY)
            case CatalogCreateStatus.CREATED:
                return SessionCreated(
                    session_id=request.session_id,
                    token=token,
                    expires_at=claims.expires_at,
                    startup_epoch=claims.startup_epoch,
                )
            case _:  # pragma: no cover - exhaustive enum
                assert_never(status)

    async def append_event(self, request: AppendEventRequest) -> EventAppendResult:
        """Authenticate, recheck expiry, hash, and append in one leased transaction."""
        initial = self._codec.validate(request.token, trusted_now(self._clock))
        match initial:
            case DemoTokenRejected(code=code):
                return EventAppendDenied(_token_code(code))
            case DemoTokenValid(claims=claims):
                lease = await self._catalog.lease(
                    claims.session_id,
                    trusted_now(self._clock),
                )
            case _:  # pragma: no cover - exhaustive token union
                assert_never(initial)
        if lease.slot is None:
            return EventAppendDenied(_lease_code(lease))
        try:
            async with lease.slot.lock:
                operation_now = trusted_now(self._clock)
                current = self._codec.validate(request.token, operation_now)
                match current:
                    case DemoTokenRejected(code=code):
                        return EventAppendDenied(_token_code(code))
                    case DemoTokenValid(claims=current_claims):
                        session_id = current_claims.session_id
                    case _:  # pragma: no cover - exhaustive token union
                        assert_never(current)
                status = await self._catalog.status(session_id, lease.slot, operation_now)
                if status is not LeaseStatus.ACTIVE:
                    return EventAppendDenied(
                        SessionAccessCode.EXPIRED
                        if status is LeaseStatus.EXPIRED
                        else SessionAccessCode.NOT_FOUND
                    )
                return append_to_slot(lease.slot, request)
        finally:
            await self._catalog.release(claims.session_id, lease.slot)

    async def access(self, request: SessionAccess) -> SessionAccessResult:
        """Authenticate and return a detached snapshot at trusted time."""
        initial = self._codec.validate(request.token, trusted_now(self._clock))
        match initial:
            case DemoTokenRejected(code=code):
                return _access_denial(_token_code(code))
            case DemoTokenValid(claims=claims):
                lease = await self._catalog.lease(
                    claims.session_id,
                    trusted_now(self._clock),
                )
            case _:  # pragma: no cover - exhaustive token union
                assert_never(initial)
        if lease.slot is None:
            return _access_denial(_lease_code(lease))
        try:
            async with lease.slot.lock:
                operation_now = trusted_now(self._clock)
                current = self._codec.validate(request.token, operation_now)
                match current:
                    case DemoTokenRejected(code=code):
                        return _access_denial(_token_code(code))
                    case DemoTokenValid(claims=current_claims):
                        session_id = current_claims.session_id
                    case _:  # pragma: no cover - exhaustive token union
                        assert_never(current)
                status = await self._catalog.status(session_id, lease.slot, operation_now)
                if status is not LeaseStatus.ACTIVE:
                    return _access_denial(
                        SessionAccessCode.EXPIRED
                        if status is LeaseStatus.EXPIRED
                        else SessionAccessCode.NOT_FOUND
                    )
                return SessionAccessGranted(
                    SessionSnapshot(
                        session_id=lease.slot.session_id,
                        startup_epoch=current_claims.startup_epoch,
                        created_at=lease.slot.created_at,
                        expires_at=lease.slot.expires_at,
                        events=tuple(lease.slot.events),
                    )
                )
        finally:
            await self._catalog.release(claims.session_id, lease.slot)

    async def live_session_count(self) -> int:
        """Return retained live/leased count at trusted time."""
        return await self._catalog.count(trusted_now(self._clock))
