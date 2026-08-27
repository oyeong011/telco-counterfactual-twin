"""Bounded session-slot catalog with cancellation-safe in-flight leases."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum, unique
from typing import TYPE_CHECKING, final

import anyio

from telco_twin.state.limits import MAX_LIVE_SESSIONS

if TYPE_CHECKING:
    from telco_twin.domain._contract import ContractId, Sha256Hex, UtcTimestamp
    from telco_twin.simulator.frozen_event import FrozenEvent
    from telco_twin.state.store_models import EventAppendAccepted


@dataclass(frozen=True, slots=True)
class IdempotencyRecord:
    """Canonical event identity and its original append result."""

    body_hash: Sha256Hex
    result: EventAppendAccepted


@final
class SessionSlot:
    """Mutable bounded state serialized by its sole AnyIO lock."""

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
        """Create one empty mutable slot with a sole AnyIO lock."""
        self.session_id = session_id
        self.created_at = created_at
        self.expires_at = expires_at
        self.events: list[FrozenEvent] = []
        self.idempotency: dict[ContractId, IdempotencyRecord] = {}
        self.lease_count = 0
        self.prune_requested = False
        self.lock = anyio.Lock()


@unique
class CatalogCreateStatus(StrEnum):
    """Closed session insertion outcomes."""

    CREATED = "created"
    EXISTS = "exists"
    CAPACITY = "capacity"


@unique
class LeaseStatus(StrEnum):
    """Closed session lease outcomes."""

    ACTIVE = "active"
    EXPIRED = "expired"
    MISSING = "missing"


@dataclass(frozen=True, slots=True)
class LeaseResult:
    """Catalog-owned slot identity and its status."""

    status: LeaseStatus
    slot: SessionSlot | None


class SessionCatalog:
    """Own slot identity, logical time, capacity, pruning, and leases."""

    _lock: anyio.Lock

    def __init__(self) -> None:
        """Create an empty bounded session catalog."""
        self._lock = anyio.Lock()
        self._sessions: dict[ContractId, SessionSlot] = {}
        self._observed_at: datetime | None = None

    def _observe(self, now: datetime) -> None:
        if self._observed_at is None or now > self._observed_at:
            self._observed_at = now

    def _expired(self, slot: SessionSlot) -> bool:
        return self._observed_at is not None and self._observed_at >= datetime.fromisoformat(
            slot.expires_at
        )

    def _prune(self) -> None:
        for session_id, slot in tuple(sorted(self._sessions.items())):
            if not self._expired(slot):
                continue
            if slot.lease_count > 0:
                slot.prune_requested = True
            else:
                del self._sessions[session_id]

    async def create(self, slot: SessionSlot, now: datetime) -> CatalogCreateStatus:
        """Insert one slot after deterministic expiry/capacity checks."""
        async with self._lock:
            self._observe(now)
            self._prune()
            if slot.session_id in self._sessions:
                return CatalogCreateStatus.EXISTS
            if len(self._sessions) >= MAX_LIVE_SESSIONS:
                return CatalogCreateStatus.CAPACITY
            self._sessions[slot.session_id] = slot
            return CatalogCreateStatus.CREATED

    async def lease(self, session_id: ContractId, now: datetime) -> LeaseResult:
        """Acquire a catalog reference before any wait on the slot lock."""
        async with self._lock:
            self._observe(now)
            self._prune()
            slot = self._sessions.get(session_id)
            if slot is None:
                return LeaseResult(LeaseStatus.MISSING, None)
            if slot.prune_requested or self._expired(slot):
                return LeaseResult(LeaseStatus.EXPIRED, None)
            slot.lease_count += 1
            return LeaseResult(LeaseStatus.ACTIVE, slot)

    async def status(
        self,
        session_id: ContractId,
        slot: SessionSlot,
        now: datetime,
    ) -> LeaseStatus:
        """Recheck exact slot identity and expiry at the locked operation instant."""
        async with self._lock:
            self._observe(now)
            self._prune()
            if self._sessions.get(session_id) is not slot:
                return LeaseStatus.MISSING
            if slot.prune_requested or self._expired(slot):
                return LeaseStatus.EXPIRED
            return LeaseStatus.ACTIVE

    async def release(self, session_id: ContractId, slot: SessionSlot) -> None:
        """Release one lease under shielded catalog cleanup."""
        with anyio.CancelScope(shield=True):
            async with self._lock:
                slot.lease_count -= 1
                if (
                    slot.lease_count == 0
                    and (slot.prune_requested or self._expired(slot))
                    and self._sessions.get(session_id) is slot
                ):
                    del self._sessions[session_id]

    async def count(self, now: datetime) -> int:
        """Return retained live/leased slots after deterministic pruning."""
        async with self._lock:
            self._observe(now)
            self._prune()
            return len(self._sessions)
