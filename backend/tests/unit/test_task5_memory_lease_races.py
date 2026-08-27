"""Deterministic session lease and pruning race regressions."""

from datetime import timedelta
from typing import final

import anyio

from telco_twin.state.limits import MAX_LIVE_SESSIONS
from telco_twin.state.memory_store import DemoSessionStore
from telco_twin.state.store_models import (
    AppendEventRequest,
    EventAppendAccepted,
    EventAppendDenied,
    SessionAccess,
    SessionAccessCode,
    SessionAccessDenied,
    SessionAccessGranted,
    SessionCreate,
    SessionCreateDenied,
)

from .test_memory_store import NOW, SECRET, store_event


@final
class _InspectableStore(DemoSessionStore):
    def session_lock(self, session_id: str) -> anyio.Lock:
        return self._sessions[session_id].lock

    def lease_count(self, session_id: str) -> int:
        return self._sessions[session_id].lease_count


async def _created_store() -> tuple[_InspectableStore, str]:
    store = _InspectableStore(signing_key=SECRET, startup_epoch="epoch-race-0001")
    created = await store.create_session(
        SessionCreate(session_id="session-race-0001", now=NOW, nonce=b"\x0b" * 16)
    )
    assert not isinstance(created, SessionCreateDenied)
    return store, created.token


def test_prune_cannot_replace_session_while_append_waits_on_slot() -> None:
    async def scenario() -> None:
        # Given: append has captured a session slot and is blocked on its lock.
        store, _ = await _created_store()
        slot_lock = store.session_lock("session-race-0001")
        outcomes: list[EventAppendAccepted | EventAppendDenied] = []

        async def append() -> None:
            outcomes.append(
                await store.append_event(
                    AppendEventRequest(
                        session_id="session-race-0001",
                        idempotency_key="idem-race-0001",
                        body_hash="a" * 64,
                        event=store_event(1),
                    )
                )
            )

        async with anyio.create_task_group() as group, slot_lock:
            _ = group.start_soon(append)
            await anyio.wait_all_tasks_blocked()
            assert slot_lock.statistics().tasks_waiting == 1
            # When: expiry pruning and same-ID recreation run while append is in flight.
            replacement = await store.create_session(
                SessionCreate(
                    session_id="session-race-0001",
                    now=NOW + timedelta(minutes=15, seconds=1),
                    nonce=b"\x0c" * 16,
                )
            )
            # Then: the leased identity cannot be replaced.
            assert isinstance(replacement, SessionCreateDenied)
        # And: TTL crossing prevents detached-slot mutation success.
        assert len(outcomes) == 1
        assert isinstance(outcomes[0], EventAppendDenied)

    anyio.run(scenario)


def test_prune_defers_removal_while_access_waits_on_slot() -> None:
    async def scenario() -> None:
        # Given: valid access has captured a session slot and is blocked on its lock.
        store, token = await _created_store()
        slot_lock = store.session_lock("session-race-0001")
        outcomes: list[SessionAccessDenied] = []

        async def access() -> None:
            result = await store.access(SessionAccess(token=token, now=NOW))
            assert isinstance(result, SessionAccessDenied)
            outcomes.append(result)

        async with anyio.create_task_group() as group, slot_lock:
            _ = group.start_soon(access)
            await anyio.wait_all_tasks_blocked()
            assert slot_lock.statistics().tasks_waiting == 1
            # When: logical time crosses TTL while access is leased.
            count = await store.live_session_count(NOW + timedelta(minutes=15, seconds=1))
            # Then: pruning is deferred until the lease releases.
            assert count == 1
            late_append = await store.append_event(
                AppendEventRequest(
                    session_id="session-race-0001",
                    idempotency_key="idem-after-expiry",
                    body_hash="2" * 64,
                    event=store_event(6),
                )
            )
            late_access = await store.access(SessionAccess(token=token, now=NOW))
            assert isinstance(late_append, EventAppendDenied)
            assert late_append.code is SessionAccessCode.NOT_FOUND
            assert isinstance(late_access, SessionAccessDenied)
            assert late_access.code is SessionAccessCode.EXPIRED
        assert len(outcomes) == 1
        # And: the expired lease is denied, then deterministically pruned.
        assert await store.live_session_count(NOW + timedelta(minutes=15, seconds=1)) == 0

    anyio.run(scenario)


def test_cancelled_append_releases_lease_before_later_prune() -> None:
    async def scenario() -> None:
        # Given: append is leased and blocked on the session lock.
        store, _ = await _created_store()
        slot_lock = store.session_lock("session-race-0001")
        scopes: list[anyio.CancelScope] = []

        async def append() -> None:
            with anyio.CancelScope() as scope:
                scopes.append(scope)
                _ = await store.append_event(
                    AppendEventRequest(
                        session_id="session-race-0001",
                        idempotency_key="idem-cancelled",
                        body_hash="d" * 64,
                        event=store_event(2),
                    )
                )

        async with anyio.create_task_group() as group, slot_lock:
            _ = group.start_soon(append)
            await anyio.wait_all_tasks_blocked()
            assert store.lease_count("session-race-0001") == 1
            # When: cancellation interrupts the lock wait.
            scopes[0].cancel()
            await anyio.wait_all_tasks_blocked()
        # Then: shielded cleanup releases the lease and future prune removes the slot.
        assert await store.live_session_count(NOW) == 1
        assert await store.live_session_count(NOW + timedelta(minutes=15, seconds=1)) == 0

    anyio.run(scenario)


def test_expired_leased_session_counts_toward_capacity_until_release() -> None:
    async def scenario() -> None:
        # Given: one access lease blocks past TTL while replacement sessions fill capacity.
        store, token = await _created_store()
        slot_lock = store.session_lock("session-race-0001")
        future = NOW + timedelta(minutes=15, seconds=1)
        outcomes: list[SessionAccessDenied] = []

        async def access() -> None:
            result = await store.access(SessionAccess(token=token, now=NOW))
            assert isinstance(result, SessionAccessDenied)
            outcomes.append(result)

        async with anyio.create_task_group() as group, slot_lock:
            _ = group.start_soon(access)
            await anyio.wait_all_tasks_blocked()
            assert await store.live_session_count(future) == 1
            for index in range(MAX_LIVE_SESSIONS - 1):
                created = await store.create_session(
                    SessionCreate(
                        session_id=f"session-future-{index:04d}",
                        now=future,
                        nonce=(index + 100).to_bytes(16, "big"),
                    )
                )
                assert not isinstance(created, SessionCreateDenied)
            overflow = await store.create_session(
                SessionCreate(
                    session_id="session-future-overflow",
                    now=future,
                    nonce=b"\xff" * 16,
                )
            )
            # When/Then: the leased expired slot still consumes bounded capacity.
            assert isinstance(overflow, SessionCreateDenied)
            assert overflow.code is SessionAccessCode.SESSION_CAPACITY
        assert outcomes[0].code is SessionAccessCode.EXPIRED
        assert await store.live_session_count(future) == MAX_LIVE_SESSIONS - 1

    anyio.run(scenario)


def test_append_and_access_after_prune_are_denied() -> None:
    async def scenario() -> None:
        # Given: a session deterministically pruned after its TTL.
        store, token = await _created_store()
        future = NOW + timedelta(minutes=15, seconds=1)
        assert await store.live_session_count(future) == 0
        # When: stale session identity and token are used.
        append = await store.append_event(
            AppendEventRequest(
                session_id="session-race-0001",
                idempotency_key="idem-after-prune",
                body_hash="e" * 64,
                event=store_event(3),
            )
        )
        access = await store.access(SessionAccess(token=token, now=future))
        # Then: neither path observes or mutates detached state.
        assert isinstance(append, EventAppendDenied)
        assert append.code is SessionAccessCode.NOT_FOUND
        assert isinstance(access, SessionAccessDenied)
        assert access.code is SessionAccessCode.EXPIRED

    anyio.run(scenario)


def test_different_sessions_progress_while_one_slot_is_blocked() -> None:
    async def scenario() -> None:
        # Given: two live sessions with only the first slot locked.
        store, _ = await _created_store()
        second = await store.create_session(
            SessionCreate(session_id="session-race-0002", now=NOW, nonce=b"\x0d" * 16)
        )
        assert not isinstance(second, SessionCreateDenied)
        first_lock = store.session_lock("session-race-0001")
        second_done = anyio.Event()

        async def append_second() -> None:
            result = await store.append_event(
                AppendEventRequest(
                    session_id="session-race-0002",
                    idempotency_key="idem-second",
                    body_hash="f" * 64,
                    event=store_event(4),
                )
            )
            assert isinstance(result, EventAppendAccepted)
            second_done.set()

        # When: the second session appends while the first remains blocked.
        async with anyio.create_task_group() as group, first_lock:
            _ = group.start_soon(append_second)
            await second_done.wait()
        # Then: per-slot locking preserves cross-session concurrency.
        access = await store.access(SessionAccess(token=second.token, now=NOW))
        assert isinstance(access, SessionAccessGranted)
        assert len(access.snapshot.events) == 1

    anyio.run(scenario)


def test_same_key_race_is_stable_across_100_stores() -> None:
    async def scenario() -> None:
        async def append(
            target: DemoSessionStore,
            target_outcomes: list[EventAppendAccepted | EventAppendDenied],
        ) -> None:
            target_outcomes.append(
                await target.append_event(
                    AppendEventRequest(
                        session_id="session-repeat",
                        idempotency_key="idem-repeat",
                        body_hash="1" * 64,
                        event=store_event(5),
                    )
                )
            )

        # Given/When: one hundred independent stores race twelve same-key appends.
        with anyio.fail_after(15):
            for repeat in range(100):
                store = DemoSessionStore(
                    signing_key=SECRET,
                    startup_epoch=f"epoch-repeat-{repeat:04d}",
                )
                created = await store.create_session(
                    SessionCreate(
                        session_id="session-repeat",
                        now=NOW,
                        nonce=repeat.to_bytes(16, "big"),
                    )
                )
                assert not isinstance(created, SessionCreateDenied)
                outcomes: list[EventAppendAccepted | EventAppendDenied] = []

                async with anyio.create_task_group() as group:
                    for _ in range(12):
                        _ = group.start_soon(append, store, outcomes)
                # Then: every repetition has one append and eleven exact replays.
                accepted = tuple(item for item in outcomes if isinstance(item, EventAppendAccepted))
                assert len(accepted) == 12
                assert sum(not item.replayed for item in accepted) == 1
                assert sum(item.replayed for item in accepted) == 11

    anyio.run(scenario)
