"""Deep immutable snapshots of validated simulator events."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, NotRequired, Self, TypedDict

from pydantic import JsonValue, TypeAdapter

from telco_twin.domain._contract import (
    ContractId,
    SafeKey,
    SchemaVersion,
    UtcTimestamp,
    VersionedExtensions,
)
from telco_twin.domain.canonical import canonical_json_bytes
from telco_twin.simulator.frozen_json import (
    JSON_VALUE_ADAPTER,
    FrozenJsonMap,
    JsonObject,
    freeze_payload,
    thaw_payload,
)

if TYPE_CHECKING:
    from telco_twin.domain.event import Event


class FrozenEventJson(TypedDict):
    """Serialized JSON shape for an immutable event snapshot."""

    event_id: ContractId
    scenario_id: ContractId
    timestamp: UtcTimestamp
    priority: int
    sequence_id: int
    event_type: SafeKey
    payload: JsonObject
    schema_version: SchemaVersion
    extensions: NotRequired[JsonValue]


FROZEN_EVENT_ADAPTER: Final[TypeAdapter[FrozenEventJson]] = TypeAdapter(FrozenEventJson)


@dataclass(frozen=True, slots=True)
class FrozenEvent:
    """Deep immutable Event snapshot with JSON round-trip support."""

    event_id: ContractId
    scenario_id: ContractId
    timestamp: UtcTimestamp
    priority: int
    sequence_id: int
    event_type: SafeKey
    payload: FrozenJsonMap
    schema_version: SchemaVersion
    extensions: VersionedExtensions | None = None

    def model_dump(self) -> FrozenEventJson:
        """Return a detached mutable JSON representation."""
        result = FrozenEventJson(
            event_id=self.event_id,
            scenario_id=self.scenario_id,
            timestamp=self.timestamp,
            priority=self.priority,
            sequence_id=self.sequence_id,
            event_type=self.event_type,
            payload=thaw_payload(self.payload),
            schema_version=self.schema_version,
        )
        if self.extensions is not None:
            result["extensions"] = JSON_VALUE_ADAPTER.validate_python(
                self.extensions.model_dump(mode="json", exclude_none=True)
            )
        return result

    def model_dump_json(self) -> str:
        """Return canonical JSON suitable for exact round-trip tests."""
        value = JSON_VALUE_ADAPTER.validate_python(self.model_dump())
        return canonical_json_bytes(value).decode()

    def model_copy(self) -> Self:
        """Return self because every reachable value is immutable."""
        return self

    @classmethod
    def model_validate_json(cls, encoded: str) -> Self:
        """Parse serialized event JSON into a recursive immutable snapshot."""
        value = FROZEN_EVENT_ADAPTER.validate_json(encoded)
        extensions = (
            VersionedExtensions.model_validate(value["extensions"])
            if "extensions" in value
            else None
        )
        return cls(
            event_id=value["event_id"],
            scenario_id=value["scenario_id"],
            timestamp=value["timestamp"],
            priority=value["priority"],
            sequence_id=value["sequence_id"],
            event_type=value["event_type"],
            payload=freeze_payload(value["payload"]),
            schema_version=value["schema_version"],
            extensions=extensions,
        )


def snapshot_event(event: Event) -> FrozenEvent:
    """Detach one validated Event from all caller-owned mutable containers."""
    payload = freeze_payload(JSON_VALUE_ADAPTER.validate_python(event.payload))
    return FrozenEvent(
        event_id=event.event_id,
        scenario_id=event.scenario_id,
        timestamp=event.timestamp,
        priority=event.priority,
        sequence_id=event.sequence_id,
        event_type=event.event_type,
        payload=payload,
        schema_version=event.schema_version,
        extensions=event.extensions,
    )
