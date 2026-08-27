"""Deterministic scheduler contract tests."""

from typing import TYPE_CHECKING, Protocol, runtime_checkable

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

if TYPE_CHECKING:
    from pydantic import JsonValue

TIED_TIMESTAMP = "2026-08-27T00:00:01Z"


@runtime_checkable
class StringSettable(Protocol):
    def __setitem__(self, key: str, value: str) -> None: ...


@runtime_checkable
class IntegerSettable(Protocol):
    def __setitem__(self, key: int, value: int) -> None: ...


def mutate_string(target: StringSettable) -> None:
    target["mode"] = "returned-mutated"


def mutate_integer(target: IntegerSettable) -> None:
    target[0] = 99


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


def test_scheduler_deeply_snapshots_payload_when_caller_and_returned_values_mutate() -> None:
    # Given: an Event carrying nested dict/list values through Pydantic model_copy.
    settings: dict[str, JsonValue] = {"mode": "original"}
    values: list[JsonValue] = [1, 2]
    nested_payload: dict[str, JsonValue] = {
        "scalars": [None, True, "text", 1, 1.5],
        "settings": settings,
        "values": values,
    }
    source = make_event(TIED_TIMESTAMP, 0, 7).model_copy(update={"payload": nested_payload})
    scheduler = DeterministicScheduler()
    scheduler.schedule(source)
    stored = scheduler.drain().events[0]
    # When: caller-owned nested values change after scheduling.
    settings["mode"] = "caller-mutated"
    values.append(3)
    source.payload["late_change"] = "caller-mutated"
    nested_map = stored.payload["settings"]
    nested_list = stored.payload["values"]
    assert isinstance(nested_map, StringSettable)
    assert isinstance(nested_list, IntegerSettable)
    # And: mutation is attempted through both returned nested containers.
    with pytest.raises(TypeError, match="immutable"):
        mutate_string(nested_map)
    with pytest.raises(TypeError, match="immutable"):
        mutate_integer(nested_list)
    # Then: the stored event remains a detached recursive snapshot.
    assert len(stored.payload) == 3
    with pytest.raises(KeyError, match="missing"):
        _ = stored.payload["missing"]
    assert stored.model_dump()["payload"] == {
        "scalars": [None, True, "text", 1, 1.5],
        "settings": {"mode": "original"},
        "values": [1, 2],
    }


def test_nested_snapshot_copy_dump_roundtrip_keeps_one_canonical_hash() -> None:
    # Given: one stored event with nested JSON values.
    source = make_event(TIED_TIMESTAMP, 0, 8).model_copy(
        update={
            "extensions": VersionedExtensions(
                schema_version="1.0",
                values={"snapshot_kind": "nested"},
            ),
            "payload": {
                "scalars": [None, True, "text", 1, 1.5],
                "settings": {"mode": "original"},
                "values": [1, 2],
            },
        }
    )
    scheduler = DeterministicScheduler()
    scheduler.schedule(source)
    stored = scheduler.drain().events[0]
    copied = stored.model_copy()
    roundtripped = type(stored).model_validate_json(stored.model_dump_json())
    dumped = stored.model_dump()
    dumped["payload"]["settings"] = {"mode": "dump-mutated"}
    dumped["payload"]["values"] = [99]
    context = HashContext(
        schema_version="1.0",
        input_name="simulation-trace",
        input_version="1.0.0",
        seed=8,
    )
    # When: each exposed representation is independently hashed.
    hashes = tuple(
        hash_trace(TraceHashInput(manifest_hash="a" * 64, events=(event,)), context)
        for event in (stored, copied, roundtripped)
    )
    # Then: copy, dump/roundtrip, and original expose one canonical event.
    assert hashes == (hashes[0],) * 3
    assert stored.model_dump() == copied.model_dump() == roundtripped.model_dump()
    assert stored.model_dump()["payload"] == {
        "scalars": [None, True, "text", 1, 1.5],
        "settings": {"mode": "original"},
        "values": [1, 2],
    }
