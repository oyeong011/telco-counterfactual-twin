"""Task 5-backed idempotent evidence append for every API mutation."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, assert_never

from telco_twin.api.errors import ProblemError
from telco_twin.api.runtime_models import ApiIdempotencyRecord
from telco_twin.domain.event import Event
from telco_twin.state.limits import MAX_EVENTS_PER_SESSION
from telco_twin.state.store_models import (
    AppendEventRequest,
    EventAppendAccepted,
    EventAppendDenied,
)
from telco_twin.state.trusted_clock import trusted_timestamp

if TYPE_CHECKING:
    from telco_twin.api.runtime import ApiRuntime, AuthorizedSession
    from telco_twin.api.runtime_models import ApiSession
    from telco_twin.domain._contract import ContractId
    from telco_twin.simulator.frozen_event import FrozenEvent


class JsonModel(Protocol):
    """Narrow serialization capability shared by Pydantic boundary models."""

    def model_dump_json(self) -> str:
        """Return a deterministic JSON representation."""
        ...


@dataclass(frozen=True, slots=True)
class MutationResult:
    """Stored mutation event plus replay metadata."""

    replayed: bool
    event: FrozenEvent


@dataclass(frozen=True, slots=True)
class EvidenceAppend:
    """Complete domain identity for one append-only API mutation."""

    idempotency_key: ContractId
    event_type: str
    body: JsonModel
    scenario_id: ContractId
    run_id: ContractId
    resource_id: ContractId


@dataclass(frozen=True, slots=True)
class IdempotencyClaim:
    """Session-wide identity fields that one idempotency key permanently owns."""

    idempotency_key: ContractId
    request_hash: str
    event_id: ContractId
    event_type: str
    scenario_id: ContractId
    run_id: ContractId
    resource_id: ContractId


def stable_id(prefix: str, session_id: str, idempotency_key: str) -> ContractId:
    """Derive an opaque stable resource ID from session-scoped idempotency."""
    digest = hashlib.sha256(f"{prefix}\0{session_id}\0{idempotency_key}".encode()).hexdigest()
    return f"{prefix}-{digest[:24]}"


def _request_hash(event_type: str, body: JsonModel) -> str:
    return hashlib.sha256(event_type.encode() + b"\0" + body.model_dump_json().encode()).hexdigest()


def _existing_event(
    events: tuple[FrozenEvent, ...],
    event_id: str,
) -> FrozenEvent | None:
    return next((event for event in events if event.event_id == event_id), None)


def idempotency_claim(session_id: ContractId, append: EvidenceAppend) -> IdempotencyClaim:
    """Build the permanent session-wide identity for one requested append."""
    return IdempotencyClaim(
        idempotency_key=append.idempotency_key,
        request_hash=_request_hash(append.event_type, append.body),
        event_id=stable_id("event", session_id, append.idempotency_key),
        event_type=append.event_type,
        scenario_id=append.scenario_id,
        run_id=append.run_id,
        resource_id=append.resource_id,
    )


def prior_idempotency(
    session: ApiSession,
    claim: IdempotencyClaim,
) -> ApiIdempotencyRecord | None:
    """Return an exact prior record or reject reuse with any different identity."""
    prior = session.idempotency.get(claim.idempotency_key)
    if prior is None:
        return None
    event = prior.event
    matches = (
        prior.request_hash == claim.request_hash
        and event.event_id == claim.event_id
        and event.event_type == claim.event_type
        and event.scenario_id == claim.scenario_id
        and event.payload.get("run_id") == claim.run_id
        and event.payload.get("resource_id") == claim.resource_id
    )
    if not matches:
        raise ProblemError(
            409,
            "idempotency_conflict",
            "Idempotency conflict",
            "The idempotency key was already used with a different request.",
        )
    return prior


def record_idempotency(
    session: ApiSession,
    claim: IdempotencyClaim,
    event: FrozenEvent,
) -> None:
    """Record the first immutable result after its append succeeds."""
    session.idempotency[claim.idempotency_key] = ApiIdempotencyRecord(
        request_hash=claim.request_hash,
        event=event,
    )


async def append_mutation(
    runtime: ApiRuntime,
    authorized: AuthorizedSession,
    append: EvidenceAppend,
) -> MutationResult:
    """Append one exact event or replay it after body/stream identity checks."""
    claim = idempotency_claim(authorized.session.session_id, append)
    prior = prior_idempotency(authorized.session, claim)
    if prior is not None:
        return MutationResult(replayed=True, event=prior.event)
    snapshot = await runtime.snapshot(authorized.token)
    existing = _existing_event(snapshot.events, claim.event_id)
    if existing is not None:
        matches = (
            existing.event_type == append.event_type
            and existing.payload.get("request_hash") == claim.request_hash
            and existing.payload.get("run_id") == append.run_id
            and existing.payload.get("resource_id") == append.resource_id
        )
        if not matches:
            raise ProblemError(
                409,
                "idempotency_conflict",
                "Idempotency conflict",
                "The idempotency key was already used with a different request.",
            )
        event = Event.model_validate(existing.model_dump())
    else:
        if authorized.session.next_event_sequence >= MAX_EVENTS_PER_SESSION:
            raise ProblemError(
                429,
                "demo_event_capacity",
                "Evidence capacity reached",
                "The bounded append-only evidence capacity is full.",
            )
        event = Event(
            event_id=claim.event_id,
            scenario_id=append.scenario_id,
            timestamp=trusted_timestamp(runtime.clock),
            priority=0,
            sequence_id=authorized.session.next_event_sequence,
            event_type=append.event_type,
            payload={
                "request_hash": claim.request_hash,
                "resource_id": append.resource_id,
                "run_id": append.run_id,
                "status": "recorded",
            },
            schema_version="1.0",
        )
    appended = await runtime.demo_store.append_event(
        AppendEventRequest(
            token=authorized.token,
            idempotency_key=append.idempotency_key,
            event=event,
        )
    )
    match appended:
        case EventAppendDenied(code=code):
            status = 409 if code.value == "idempotency_conflict" else 429
            raise ProblemError(
                status,
                code.value,
                "Evidence append denied",
                "The bounded append-only store denied the mutation.",
            )
        case EventAppendAccepted():
            if not appended.replayed:
                authorized.session.next_event_sequence += 1
            record_idempotency(authorized.session, claim, appended.event)
            return MutationResult(appended.replayed, appended.event)
        case _:
            assert_never(appended)
