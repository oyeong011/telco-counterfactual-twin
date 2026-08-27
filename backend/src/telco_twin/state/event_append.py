"""Canonical event hashing, idempotency, capacity, and append mutation."""

from __future__ import annotations

import hashlib

from telco_twin.simulator.frozen_event import snapshot_event
from telco_twin.state.limits import MAX_EVENTS_PER_SESSION
from telco_twin.state.session_catalog import IdempotencyRecord, SessionSlot
from telco_twin.state.store_models import (
    AppendEventRequest,
    EventAppendAccepted,
    EventAppendDenied,
    EventAppendResult,
    SessionAccessCode,
)


def append_to_slot(
    slot: SessionSlot,
    request: AppendEventRequest,
) -> EventAppendResult:
    """Recompute canonical identity and perform one locked idempotent append."""
    frozen_event = snapshot_event(request.event)
    body_hash = hashlib.sha256(frozen_event.model_dump_json().encode()).hexdigest()
    prior = slot.idempotency.get(request.idempotency_key)
    if prior is not None:
        if prior.body_hash != body_hash:
            return EventAppendDenied(SessionAccessCode.IDEMPOTENCY_CONFLICT)
        return EventAppendAccepted(event=prior.result.event, replayed=True)
    if len(slot.events) >= MAX_EVENTS_PER_SESSION:
        return EventAppendDenied(SessionAccessCode.EVENT_CAPACITY)
    accepted = EventAppendAccepted(event=frozen_event, replayed=False)
    slot.events.append(frozen_event)
    slot.idempotency[request.idempotency_key] = IdempotencyRecord(
        body_hash=body_hash,
        result=accepted,
    )
    return accepted
