"""Immutable scalar snapshots of validated simulator events."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Final, Never, NotRequired, Self, TypedDict, override

from pydantic import JsonValue, TypeAdapter

from telco_twin.domain._contract import (
    ContractId,
    JsonScalar,
    PropertyMap,
    SafeKey,
    SchemaVersion,
    UtcTimestamp,
)
from telco_twin.domain.canonical import canonical_json_bytes
from telco_twin.domain.event import Event


@dataclass(frozen=True, slots=True)
class FrozenMutationError(TypeError):
    """A caller attempted to mutate append-only event state."""

    field_name: str

    @override
    def __str__(self) -> str:
        """Return a stable immutable-field diagnostic."""
        return f"frozen event {self.field_name} is immutable"


@dataclass(frozen=True, slots=True)
class FrozenScalarMap(Mapping[str, JsonScalar]):
    """Immutable canonical-order view of validated scalar properties."""

    _entries: tuple[tuple[str, JsonScalar], ...]

    @override
    def __getitem__(self, key: str) -> JsonScalar:
        """Return one scalar by key."""
        for candidate, value in self._entries:
            if candidate == key:
                return value
        raise KeyError(key)

    @override
    def __iter__(self) -> Iterator[str]:
        """Iterate keys in canonical lexical order."""
        return (key for key, _ in self._entries)

    @override
    def __len__(self) -> int:
        """Return the fixed entry count."""
        return len(self._entries)

    def __setitem__(self, key: str, value: JsonScalar) -> Never:
        """Reject mutation through mapping syntax."""
        raise FrozenMutationError(field_name="properties")


class FrozenExtensionsJson(TypedDict):
    """Detached JSON projection of immutable extension metadata."""

    schema_version: SchemaVersion
    values: PropertyMap


@dataclass(frozen=True, slots=True)
class FrozenExtensions:
    """Immutable snapshot of validated versioned extension scalars."""

    schema_version: SchemaVersion
    values: FrozenScalarMap

    def model_dump(self) -> FrozenExtensionsJson:
        """Return a detached mutable JSON projection."""
        return FrozenExtensionsJson(
            schema_version=self.schema_version,
            values=_thaw_properties(self.values),
        )


class FrozenEventJson(TypedDict):
    """Serialized JSON shape for an immutable Event snapshot."""

    event_id: ContractId
    scenario_id: ContractId
    timestamp: UtcTimestamp
    priority: int
    sequence_id: int
    event_type: SafeKey
    payload: PropertyMap
    schema_version: SchemaVersion
    extensions: NotRequired[FrozenExtensionsJson]


JSON_VALUE_ADAPTER: Final[TypeAdapter[JsonValue]] = TypeAdapter(JsonValue)


def _freeze_properties(values: Mapping[str, JsonScalar]) -> FrozenScalarMap:
    return FrozenScalarMap(tuple((key, values[key]) for key in sorted(values)))


def _thaw_properties(values: FrozenScalarMap) -> PropertyMap:
    return dict(values.items())


@dataclass(frozen=True, slots=True)
class FrozenEvent:
    """Deep immutable scalar snapshot of one authoritative Event."""

    event_id: ContractId
    scenario_id: ContractId
    timestamp: UtcTimestamp
    priority: int
    sequence_id: int
    event_type: SafeKey
    payload: FrozenScalarMap
    schema_version: SchemaVersion
    extensions: FrozenExtensions | None = None

    def model_dump(self) -> FrozenEventJson:
        """Return a detached mutable JSON representation."""
        result = FrozenEventJson(
            event_id=self.event_id,
            scenario_id=self.scenario_id,
            timestamp=self.timestamp,
            priority=self.priority,
            sequence_id=self.sequence_id,
            event_type=self.event_type,
            payload=_thaw_properties(self.payload),
            schema_version=self.schema_version,
        )
        if self.extensions is not None:
            result["extensions"] = self.extensions.model_dump()
        return result

    def model_dump_json(self) -> str:
        """Return canonical JSON suitable for exact round-trip tests."""
        value = JSON_VALUE_ADAPTER.validate_python(self.model_dump())
        return canonical_json_bytes(value).decode()

    def model_copy(self) -> Self:
        """Return self because every reachable value is immutable."""
        return self

    @staticmethod
    def model_validate_json(encoded: str) -> FrozenEvent:
        """Validate through Event before creating an immutable snapshot."""
        return snapshot_event(Event.model_validate_json(encoded))


def snapshot_event(event: Event) -> FrozenEvent:
    """Detach validated scalar payload and extension mappings."""
    extensions = (
        FrozenExtensions(
            schema_version=event.extensions.schema_version,
            values=_freeze_properties(event.extensions.values),
        )
        if event.extensions is not None
        else None
    )
    return FrozenEvent(
        event_id=event.event_id,
        scenario_id=event.scenario_id,
        timestamp=event.timestamp,
        priority=event.priority,
        sequence_id=event.sequence_id,
        event_type=event.event_type,
        payload=_freeze_properties(event.payload),
        schema_version=event.schema_version,
        extensions=extensions,
    )
