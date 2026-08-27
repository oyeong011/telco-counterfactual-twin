"""Bounded append-only demo session store tests."""

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
    SessionCreateDenied,
)

NOW = datetime(2026, 8, 27, 0, 0, 0, tzinfo=UTC)
SECRET = DemoTokenKey(b"demo-token-test-key-material-32b")


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


def _store(epoch: str = "epoch-0001") -> DemoSessionStore:
    return DemoSessionStore(signing_key=SECRET, startup_epoch=epoch)


def test_idempotency_replays_same_body_and_conflicts_on_different_body() -> None:
    async def scenario() -> None:
        # Given: one live session and one idempotent append.
        store = _store()
        created = await store.create_session(
            SessionCreate(session_id="session-0001", now=NOW, nonce=b"\x01" * 16)
        )
        assert not isinstance(created, SessionCreateDenied)
        first = await store.append_event(
            AppendEventRequest(
                session_id="session-0001",
                idempotency_key="idem-0001",
                body_hash="a" * 64,
                event=store_event(1),
            )
        )
        # When: the same key is retried with the same and then a different body hash.
        replay = await store.append_event(
            AppendEventRequest(
                session_id="session-0001",
                idempotency_key="idem-0001",
                body_hash="a" * 64,
                event=store_event(1),
            )
        )
        conflict = await store.append_event(
            AppendEventRequest(
                session_id="session-0001",
                idempotency_key="idem-0001",
                body_hash="b" * 64,
                event=store_event(2),
            )
        )
        access = await store.access(SessionAccess(token=created.token, now=NOW))
        # Then: replay returns the original result and conflict never appends.
        assert isinstance(first, EventAppendAccepted)
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
        # Given: one live session and twenty equal idempotent requests.
        store = _store()
        created = await store.create_session(
            SessionCreate(session_id="session-0001", now=NOW, nonce=b"\x02" * 16)
        )
        assert not isinstance(created, SessionCreateDenied)
        outcomes: list[EventAppendAccepted | EventAppendDenied] = []

        async def append_once() -> None:
            outcome = await store.append_event(
                AppendEventRequest(
                    session_id="session-0001",
                    idempotency_key="idem-shared",
                    body_hash="c" * 64,
                    event=store_event(1),
                )
            )
            outcomes.append(outcome)

        # When: every request races through the session's AnyIO lock.
        async with anyio.create_task_group() as group:
            for _ in range(20):
                _ = group.start_soon(append_once)
        access = await store.access(SessionAccess(token=created.token, now=NOW))
        # Then: one append and nineteen same-body replays are observable.
        assert all(isinstance(item, EventAppendAccepted) for item in outcomes)
        assert (
            sum(not item.replayed for item in outcomes if isinstance(item, EventAppendAccepted))
            == 1
        )
        assert isinstance(access, SessionAccessGranted)
        assert len(access.snapshot.events) == 1

    anyio.run(scenario)


def test_parallel_distinct_idempotency_keys_append_without_races() -> None:
    async def scenario() -> None:
        # Given: one live session and twenty independent event requests.
        store = _store()
        created = await store.create_session(
            SessionCreate(session_id="session-0001", now=NOW, nonce=b"\x03" * 16)
        )
        assert not isinstance(created, SessionCreateDenied)

        async def append_one(index: int) -> None:
            _ = await store.append_event(
                AppendEventRequest(
                    session_id="session-0001",
                    idempotency_key=f"idem-{index:04d}",
                    body_hash=f"{index:064x}",
                    event=store_event(index),
                )
            )

        # When: distinct keys are appended concurrently.
        async with anyio.create_task_group() as group:
            for index in range(20):
                _ = group.start_soon(append_one, index)
        access = await store.access(SessionAccess(token=created.token, now=NOW))
        # Then: every event is retained once in deterministic append order.
        assert isinstance(access, SessionAccessGranted)
        assert len(access.snapshot.events) == 20
        assert len({event.event_id for event in access.snapshot.events}) == 20

    anyio.run(scenario)


def test_live_capacity_is_bounded_and_expired_sessions_are_pruned() -> None:
    async def scenario() -> None:
        # Given: the exact maximum number of live demo sessions.
        store = _store()
        for index in range(MAX_LIVE_SESSIONS):
            outcome = await store.create_session(
                SessionCreate(
                    session_id=f"session-{index:04d}",
                    now=NOW,
                    nonce=index.to_bytes(16, "big"),
                )
            )
            assert not isinstance(outcome, SessionCreateDenied)
        # When: another session is requested before and after the fixed TTL.
        blocked = await store.create_session(
            SessionCreate(session_id="session-overflow", now=NOW, nonce=b"\xfe" * 16)
        )
        replacement = await store.create_session(
            SessionCreate(
                session_id="session-replacement",
                now=NOW + timedelta(minutes=15, seconds=1),
                nonce=b"\xff" * 16,
            )
        )
        # Then: live capacity fails closed while expired entries are deterministically pruned.
        assert isinstance(blocked, SessionCreateDenied)
        assert blocked.code is SessionAccessCode.SESSION_CAPACITY
        assert not isinstance(replacement, SessionCreateDenied)
        assert await store.live_session_count(NOW + timedelta(minutes=15, seconds=1)) == 1

    anyio.run(scenario)


def test_event_capacity_is_append_only_and_bounded_at_256() -> None:
    async def scenario() -> None:
        # Given: one session filled to the exact event ceiling.
        store = _store()
        created = await store.create_session(
            SessionCreate(session_id="session-0001", now=NOW, nonce=b"\x04" * 16)
        )
        assert not isinstance(created, SessionCreateDenied)
        for index in range(MAX_EVENTS_PER_SESSION):
            result = await store.append_event(
                AppendEventRequest(
                    session_id="session-0001",
                    idempotency_key=f"idem-{index:04d}",
                    body_hash=f"{index:064x}",
                    event=store_event(index),
                )
            )
            assert isinstance(result, EventAppendAccepted)
        # When: a 257th event is appended.
        overflow = await store.append_event(
            AppendEventRequest(
                session_id="session-0001",
                idempotency_key="idem-overflow",
                body_hash="f" * 64,
                event=store_event(MAX_EVENTS_PER_SESSION),
            )
        )
        access = await store.access(SessionAccess(token=created.token, now=NOW))
        # Then: no prior event is evicted or mutated.
        assert isinstance(overflow, EventAppendDenied)
        assert overflow.code is SessionAccessCode.EVENT_CAPACITY
        assert isinstance(access, SessionAccessGranted)
        assert len(access.snapshot.events) == MAX_EVENTS_PER_SESSION

    anyio.run(scenario)


def test_evidence_snapshot_is_detached_from_caller_alias_mutation() -> None:
    async def scenario() -> None:
        # Given: an event whose caller-owned payload remains mutable.
        store = _store()
        created = await store.create_session(
            SessionCreate(session_id="session-0001", now=NOW, nonce=b"\x05" * 16)
        )
        assert not isinstance(created, SessionCreateDenied)
        event = store_event(1)
        _ = await store.append_event(
            AppendEventRequest(
                session_id="session-0001",
                idempotency_key="idem-0001",
                body_hash="1" * 64,
                event=event,
            )
        )
        # When: the source payload is changed after append and evidence is downloaded.
        event.payload["index"] = 999
        access = await store.access(SessionAccess(token=created.token, now=NOW))
        # Then: the immutable stored snapshot retains the append-time value.
        assert isinstance(access, SessionAccessGranted)
        assert access.snapshot.events[0].payload["index"] == 1

    anyio.run(scenario)
