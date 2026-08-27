"""Bounded authenticated append-only demo session store tests."""

from datetime import UTC, datetime, timedelta

import anyio

from telco_twin.domain.event import Event
from telco_twin.state.demo_token import DemoTokenKey
from telco_twin.state.limits import MAX_EVENTS_PER_SESSION, MAX_LIVE_SESSIONS
from telco_twin.state.memory_store import DemoSessionStore
from telco_twin.state.store_models import (
    AppendEventRequest,
    EventAppendAccepted,
    EventAppendDenied,
    SessionAccess,
    SessionAccessCode,
    SessionAccessGranted,
    SessionCreate,
    SessionCreated,
    SessionCreateDenied,
)

NOW = datetime(2026, 8, 27, 0, 0, 0, tzinfo=UTC)
SECRET = DemoTokenKey(b"demo-token-test-key-material-32b")


class MutableClock:
    """Deterministic store-owned clock advanced explicitly by tests."""

    def __init__(self, current: datetime = NOW) -> None:
        self.current: datetime = current

    def now(self) -> datetime:
        return self.current

    def advance_to(self, current: datetime) -> None:
        self.current = current


def store_event(index: int) -> Event:
    return Event(
        event_id=f"event-{index:04d}",
        scenario_id="scenario-0001",
        timestamp="2026-08-27T00:00:00Z",
        priority=0,
        sequence_id=index,
        event_type="evidence-recorded",
        payload={"index": index},
        schema_version="1.0",
    )


def demo_store(
    epoch: str = "epoch-0001",
    clock: MutableClock | None = None,
) -> DemoSessionStore:
    return DemoSessionStore(
        signing_key=SECRET,
        startup_epoch=epoch,
        clock=clock or MutableClock(),
    )


async def created_session(
    store: DemoSessionStore,
    nonce: bytes = b"\x01" * 16,
) -> SessionCreated:
    result = await store.create_session(SessionCreate(session_id="session-0001", nonce=nonce))
    assert isinstance(result, SessionCreated)
    return result


def _append(token: str, key: str, index: int) -> AppendEventRequest:
    return AppendEventRequest(
        token=token,
        idempotency_key=key,
        event=store_event(index),
    )


def test_idempotency_replays_same_body_and_conflicts_on_different_body() -> None:
    async def scenario() -> None:
        store = demo_store()
        created = await created_session(store)
        first = await store.append_event(_append(created.token, "idem-0001", 1))
        replay = await store.append_event(_append(created.token, "idem-0001", 1))
        conflict = await store.append_event(_append(created.token, "idem-0001", 2))
        access = await store.access(SessionAccess(token=created.token))
        assert isinstance(first, EventAppendAccepted)
        assert "token" not in first.__dataclass_fields__
        assert isinstance(replay, EventAppendAccepted)
        assert replay.replayed is True
        assert replay.event == first.event
        assert isinstance(conflict, EventAppendDenied)
        assert conflict.code is SessionAccessCode.IDEMPOTENCY_CONFLICT
        assert isinstance(access, SessionAccessGranted)
        assert access.snapshot.events == (first.event,)

    anyio.run(scenario)


def test_parallel_same_idempotency_key_appends_exactly_once() -> None:
    async def scenario() -> None:
        store = demo_store()
        created = await created_session(store, b"\x02" * 16)
        outcomes: list[EventAppendAccepted | EventAppendDenied] = []

        async def append_once() -> None:
            outcomes.append(await store.append_event(_append(created.token, "idem-shared", 1)))

        async with anyio.create_task_group() as group:
            for _ in range(20):
                _ = group.start_soon(append_once)
        access = await store.access(SessionAccess(token=created.token))
        assert all(isinstance(item, EventAppendAccepted) for item in outcomes)
        accepted = tuple(item for item in outcomes if isinstance(item, EventAppendAccepted))
        assert sum(not item.replayed for item in accepted) == 1
        assert isinstance(access, SessionAccessGranted)
        assert len(access.snapshot.events) == 1

    anyio.run(scenario)


def test_parallel_distinct_idempotency_keys_append_without_races() -> None:
    async def scenario() -> None:
        store = demo_store()
        created = await created_session(store, b"\x03" * 16)

        async def append_one(index: int) -> None:
            _ = await store.append_event(_append(created.token, f"idem-{index:04d}", index))

        async with anyio.create_task_group() as group:
            for index in range(20):
                _ = group.start_soon(append_one, index)
        access = await store.access(SessionAccess(token=created.token))
        assert isinstance(access, SessionAccessGranted)
        assert len(access.snapshot.events) == 20
        assert len({event.event_id for event in access.snapshot.events}) == 20

    anyio.run(scenario)


def test_live_capacity_is_bounded_and_expired_sessions_are_pruned() -> None:
    async def scenario() -> None:
        clock = MutableClock()
        store = demo_store(clock=clock)
        for index in range(MAX_LIVE_SESSIONS):
            result = await store.create_session(
                SessionCreate(
                    session_id=f"session-{index:04d}",
                    nonce=index.to_bytes(16, "big"),
                )
            )
            assert not isinstance(result, SessionCreateDenied)
        blocked = await store.create_session(
            SessionCreate(session_id="session-overflow", nonce=b"\xfe" * 16)
        )
        clock.advance_to(NOW + timedelta(minutes=15, seconds=1))
        replacement = await store.create_session(
            SessionCreate(session_id="session-replacement", nonce=b"\xff" * 16)
        )
        assert isinstance(blocked, SessionCreateDenied)
        assert blocked.code is SessionAccessCode.SESSION_CAPACITY
        assert not isinstance(replacement, SessionCreateDenied)
        assert await store.live_session_count() == 1

    anyio.run(scenario)


def test_event_capacity_is_append_only_and_bounded_at_256() -> None:
    async def scenario() -> None:
        store = demo_store()
        created = await created_session(store, b"\x04" * 16)
        for index in range(MAX_EVENTS_PER_SESSION):
            result = await store.append_event(_append(created.token, f"idem-{index:04d}", index))
            assert isinstance(result, EventAppendAccepted)
        overflow = await store.append_event(
            _append(created.token, "idem-overflow", MAX_EVENTS_PER_SESSION)
        )
        access = await store.access(SessionAccess(token=created.token))
        assert isinstance(overflow, EventAppendDenied)
        assert overflow.code is SessionAccessCode.EVENT_CAPACITY
        assert isinstance(access, SessionAccessGranted)
        assert len(access.snapshot.events) == MAX_EVENTS_PER_SESSION

    anyio.run(scenario)


def test_evidence_snapshot_is_detached_from_caller_alias_mutation() -> None:
    async def scenario() -> None:
        store = demo_store()
        created = await created_session(store, b"\x05" * 16)
        event = store_event(1)
        _ = await store.append_event(
            AppendEventRequest(
                token=created.token,
                idempotency_key="idem-0001",
                event=event,
            )
        )
        event.payload["index"] = 999
        access = await store.access(SessionAccess(token=created.token))
        assert isinstance(access, SessionAccessGranted)
        assert access.snapshot.events[0].payload["index"] == 1

    anyio.run(scenario)
