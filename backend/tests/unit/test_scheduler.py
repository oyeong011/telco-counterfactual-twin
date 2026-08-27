"""Deterministic scheduler contract tests."""

from typing import Protocol, runtime_checkable

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from telco_twin.domain._contract import VersionedExtensions
from telco_twin.domain.event import Event
from telco_twin.simulator.hashing import HashContext, TraceHashInput, hash_trace
from telco_twin.simulator.scheduler import (
    DeterministicScheduler,
    DuplicateSequenceError,
    EventTrace,
)

TIED_TIMESTAMP = "2026-08-27T00:00:01Z"


@runtime_checkable
class StringSettable(Protocol):
    def __setitem__(self, key: str, value: str) -> None: ...


def mutate_string(target: StringSettable) -> None:
    target["mode"] = "returned-mutated"


def make_event(timestamp: str, priority: int, sequence_id: int) -> Event:
    return Event(
        event_id=f"event-{sequence_id:04d}",
        scenario_id="scenario-0001",
        timestamp=timestamp,
        priority=priority,
        sequence_id=sequence_id,
        event_type="test-event",
        payload={},
        schema_version="1.0",
    )


def make_extension_event(sequence_id: int) -> Event:
    return Event(
        event_id=f"event-{sequence_id:04d}",
        scenario_id="scenario-0001",
        timestamp=TIED_TIMESTAMP,
        priority=0,
        sequence_id=sequence_id,
        event_type="extension-test",
        payload={"count": 1},
        extensions=VersionedExtensions(
            schema_version="1.0",
            values={"flag": "original"},
        ),
        schema_version="1.0",
    )


def test_scheduler_orders_by_timestamp_priority_sequence_when_events_tie() -> None:
    # Given: events whose keys require every stable-priority tuple component.
    events = (
        make_event("2026-08-27T00:00:02Z", -10, 3),
        make_event(TIED_TIMESTAMP, 10, 2),
        make_event(TIED_TIMESTAMP, 10, 1),
        make_event(TIED_TIMESTAMP, 0, 4),
    )
    scheduler = DeterministicScheduler()
    for event in events:
        scheduler.schedule(event)
    # When: the queue is drained.
    trace = scheduler.drain()
    # Then: ordering is exactly timestamp, priority, sequence identifier.
    assert tuple(
        (event.timestamp, event.priority, event.sequence_id) for event in trace.events
    ) == (
        (TIED_TIMESTAMP, 0, 4),
        (TIED_TIMESTAMP, 10, 1),
        (TIED_TIMESTAMP, 10, 2),
        ("2026-08-27T00:00:02Z", -10, 3),
    )


@settings(max_examples=100, derandomize=True)
@given(
    order=st.lists(
        st.tuples(
            st.integers(min_value=-1000, max_value=1000),
            st.integers(min_value=0, max_value=(2**32) - 1),
        ),
        min_size=1,
        max_size=20,
        unique_by=lambda key: key[1],
    )
)
def test_scheduler_tie_order_is_stable_when_insertion_order_varies(
    order: list[tuple[int, int]],
) -> None:
    # Given: one of 100 generated insertion orders for tied timestamps.
    scheduler = DeterministicScheduler()
    for priority, sequence_id in order:
        scheduler.schedule(make_event(TIED_TIMESTAMP, priority, sequence_id))
    # When: the tied queue is drained.
    result = tuple((event.priority, event.sequence_id) for event in scheduler.drain().events)
    # Then: insertion order cannot change the priority/sequence ordering.
    assert result == tuple(sorted(order))


def test_scheduler_rejects_duplicate_sequence_when_keys_could_collide() -> None:
    # Given: a scheduler containing sequence identifier 1.
    scheduler = DeterministicScheduler()
    scheduler.schedule(make_event(TIED_TIMESTAMP, 0, 1))
    # When: another event reuses that sequence identifier.
    with pytest.raises(DuplicateSequenceError, match="sequence identifier 1"):
        scheduler.schedule(make_event("2026-08-27T00:00:02Z", 10, 1))
    # Then: only the original event remains observable.
    assert scheduler.drain().events[0].event_id == "event-0001"


def test_event_trace_appends_without_mutating_prior_versions() -> None:
    # Given: an empty immutable trace and two events.
    empty = EventTrace()
    first = make_event(TIED_TIMESTAMP, 0, 1)
    second = make_event(TIED_TIMESTAMP, 0, 2)
    # When: successive trace versions append one event.
    one_event = empty.append(first)
    two_events = one_event.append(second)
    # Then: earlier versions remain unchanged and ordered.
    assert empty.events == ()
    assert tuple(event.event_id for event in one_event.events) == ("event-0001",)
    assert tuple(event.event_id for event in two_events.events) == ("event-0001", "event-0002")


def test_scheduler_snapshots_valid_payload_and_extension_values() -> None:
    # Given: a fully validated Event with scalar payload and extension values.
    source = make_extension_event(7)
    scheduler = DeterministicScheduler()
    scheduler.schedule(source)
    stored = scheduler.drain().events[0]
    # When: caller-owned payload and extension mappings change after scheduling.
    source.payload["count"] = 2
    source.payload["late_change"] = "caller-mutated"
    assert source.extensions is not None
    source.extensions.values["flag"] = "caller-mutated"
    assert stored.extensions is not None
    assert isinstance(stored.payload, StringSettable)
    assert isinstance(stored.extensions.values, StringSettable)
    # And: mutation is attempted through both returned mappings.
    with pytest.raises(TypeError, match="immutable"):
        mutate_string(stored.payload)
    with pytest.raises(TypeError, match="immutable"):
        mutate_string(stored.extensions.values)
    # Then: the stored event remains a detached scalar snapshot.
    assert stored.model_dump() == {
        "event_id": "event-0007",
        "scenario_id": "scenario-0001",
        "timestamp": TIED_TIMESTAMP,
        "priority": 0,
        "sequence_id": 7,
        "event_type": "extension-test",
        "payload": {"count": 1},
        "schema_version": "1.0",
        "extensions": {
            "schema_version": "1.0",
            "values": {"flag": "original"},
        },
    }


def test_extension_snapshot_copy_dump_roundtrip_keeps_one_canonical_hash() -> None:
    # Given: one stored Event with fully validated extension values.
    source = make_extension_event(8)
    scheduler = DeterministicScheduler()
    scheduler.schedule(source)
    stored = scheduler.drain().events[0]
    context = HashContext(
        schema_version="1.0",
        input_name="simulation-trace",
        input_version="1.0.0",
        seed=8,
    )
    before = hash_trace(TraceHashInput(manifest_hash="a" * 64, events=(stored,)), context)
    assert source.extensions is not None
    source.extensions.values["flag"] = "caller-mutated"
    copied = stored.model_copy()
    roundtripped = type(stored).model_validate_json(stored.model_dump_json())
    dumped = stored.model_dump()
    dumped["payload"]["count"] = 99
    dumped["extensions"] = {
        "schema_version": "1.0",
        "values": {"flag": "dump-mutated"},
    }
    # When: each exposed representation is independently hashed.
    hashes = tuple(
        hash_trace(TraceHashInput(manifest_hash="a" * 64, events=(event,)), context)
        for event in (stored, copied, roundtripped)
    )
    # Then: copy, dump/roundtrip, and original expose one canonical event.
    assert (before, *hashes) == (before,) * 4
    assert stored.model_dump() == copied.model_dump() == roundtripped.model_dump()
    assert stored.model_dump()["payload"] == {"count": 1}
    assert stored.model_dump().get("extensions") == {
        "schema_version": "1.0",
        "values": {"flag": "original"},
    }
