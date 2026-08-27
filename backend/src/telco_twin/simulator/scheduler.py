"""Stable discrete-event priority scheduler."""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Self, override

if TYPE_CHECKING:
    from telco_twin.domain.event import Event


@dataclass(frozen=True, slots=True)
class DuplicateSequenceError(Exception):
    """A scheduler sequence identifier was reused."""

    sequence_id: int

    @override
    def __str__(self) -> str:
        """Return a stable diagnostic without event payload data."""
        return f"sequence identifier {self.sequence_id} is already scheduled"


@dataclass(order=True, frozen=True, slots=True)
class _QueueEntry:
    """Heap entry whose comparison key is exactly the accepted priority tuple."""

    timestamp: str
    priority: int
    sequence_id: int
    event: Event = field(compare=False)


@dataclass(frozen=True, slots=True)
class EventTrace:
    """One immutable version in an append-only event trace."""

    events: tuple[Event, ...] = ()

    def append(self, event: Event) -> Self:
        """Return a new trace containing one additional event."""
        return type(self)(events=(*self.events, event))


class DeterministicScheduler:
    """Mutable queue isolated to one run; drained output is immutable."""

    def __init__(self) -> None:
        """Create an empty queue and isolated sequence registry."""
        self._queue: list[_QueueEntry] = []
        self._sequence_ids: set[int] = set()

    def schedule(self, event: Event) -> None:
        """Schedule an immutable event once by global sequence identifier."""
        if event.sequence_id in self._sequence_ids:
            raise DuplicateSequenceError(sequence_id=event.sequence_id)
        self._sequence_ids.add(event.sequence_id)
        heapq.heappush(
            self._queue,
            _QueueEntry(
                timestamp=event.timestamp,
                priority=event.priority,
                sequence_id=event.sequence_id,
                event=event,
            ),
        )

    def drain(self) -> EventTrace:
        """Consume the queue into a stable append-only trace."""
        trace = EventTrace()
        while self._queue:
            trace = trace.append(heapq.heappop(self._queue).event)
        return trace
