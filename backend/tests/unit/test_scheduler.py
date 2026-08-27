"""Deterministic scheduler contract tests."""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from telco_twin.domain.event import Event
from telco_twin.simulator.scheduler import (
    DeterministicScheduler,
    DuplicateSequenceError,
    EventTrace,
)

TIED_TIMESTAMP = "2026-08-27T00:00:01Z"


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
    assert scheduler.drain().events == (make_event(TIED_TIMESTAMP, 0, 1),)


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
    assert one_event.events == (first,)
    assert two_events.events == (first, second)
