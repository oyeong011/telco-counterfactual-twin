"""Versioned RFC 8785 hashes for simulator inputs and traces."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, override

from pydantic import BaseModel, JsonValue, TypeAdapter

from telco_twin.domain._contract import (
    SafeKey,
    SchemaVersion,
    Seed,
    SemanticVersion,
    Sha256Hex,
    StrictContract,
)
from telco_twin.domain.canonical import canonical_json_bytes, canonical_model_bytes

if TYPE_CHECKING:
    from telco_twin.domain.event import Event

JSON_VALUE_ADAPTER: Final[TypeAdapter[JsonValue]] = TypeAdapter(JsonValue)


@dataclass(frozen=True, slots=True)
class EmptyTraceError(Exception):
    """A trace without events cannot receive a success digest."""

    @override
    def __str__(self) -> str:
        """Return a stable nonempty-trace diagnostic."""
        return "simulation trace requires at least one event"


class HashContext(StrictContract):
    """Digest-bearing identity for one canonical simulator input."""

    schema_version: SchemaVersion
    input_name: SafeKey
    input_version: SemanticVersion
    seed: Seed


class _HashEnvelope(StrictContract):
    """Canonical boundary that binds metadata to one content digest."""

    schema_version: SchemaVersion
    input_name: SafeKey
    input_version: SemanticVersion
    seed: Seed
    input_hash: Sha256Hex


@dataclass(frozen=True, slots=True)
class TraceHashInput:
    """Nonempty append-only trace bound to its immutable manifest."""

    manifest_hash: Sha256Hex
    events: tuple[Event, ...]

    def __post_init__(self) -> None:
        """Reject success-shaped traces without observable events."""
        if not self.events:
            raise EmptyTraceError


def _hash_input(input_hash: Sha256Hex, context: HashContext) -> Sha256Hex:
    envelope = _HashEnvelope(
        schema_version=context.schema_version,
        input_name=context.input_name,
        input_version=context.input_version,
        seed=context.seed,
        input_hash=input_hash,
    )
    return hashlib.sha256(canonical_model_bytes(envelope)).hexdigest()


def hash_contract(
    model: BaseModel,
    context: HashContext,
    *,
    exclude: frozenset[str] | None = None,
) -> Sha256Hex:
    """Hash canonical model bytes inside a versioned simulator envelope."""
    input_hash = hashlib.sha256(canonical_model_bytes(model, exclude=exclude)).hexdigest()
    return _hash_input(input_hash, context)


def hash_trace(trace: TraceHashInput, context: HashContext) -> Sha256Hex:
    """Hash a nonempty trace with the same canonical metadata boundary."""
    value = JSON_VALUE_ADAPTER.validate_python(
        {
            "schema_version": context.schema_version,
            "manifest_hash": trace.manifest_hash,
            "events": [event.model_dump(mode="json", exclude_none=True) for event in trace.events],
        }
    )
    input_hash = hashlib.sha256(canonical_json_bytes(value)).hexdigest()
    return _hash_input(input_hash, context)
