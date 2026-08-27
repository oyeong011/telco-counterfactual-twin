"""Deterministic authenticated session lease/pruning race regressions."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, final, override

import anyio

from telco_twin.state.limits import MAX_LIVE_SESSIONS
from telco_twin.state.memory_store import DemoSessionStore
from telco_twin.state.session_catalog import SessionCatalog
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

from .test_memory_store import NOW, SECRET, MutableClock, store_event

if TYPE_CHECKING:
    from telco_twin.domain._contract import ContractId
    from telco_twin.state.demo_token import DemoTokenKey
    from telco_twin.state.trusted_clock import TrustedClock


@final
class _InspectableCatalog(SessionCatalog):
    def session_lock(self, session_id: str) -> anyio.Lock:
        return self._sessions[session_id].lock

    def lease_count(self, session_id: str) -> int:
        return self._sessions[session_id].lease_count


@final
class _InspectableStore(DemoSessionStore):
    @override
    def __init__(
        self,
        *,
        signing_key: DemoTokenKey,
        startup_epoch: ContractId,
        clock: TrustedClock,
    ) -> None:
        super().__init__(
            signing_key=signing_key,
            startup_epoch=startup_epoch,
            clock=clock,
        )
        self._inspectable_catalog = _InspectableCatalog()
        self._catalog = self._inspectable_catalog

    def session_lock(self, session_id: str) -> anyio.Lock:
        return self._inspectable_catalog.session_lock(session_id)

    def lease_count(self, session_id: str) -> int:
        return self._inspectable_catalog.lease_count(session_id)


async def _created_store() -> tuple[_InspectableStore, MutableClock, str]:
    clock = MutableClock()
    store = _InspectableStore(
        signing_key=SECRET,
        startup_epoch="epoch-race-0001",
        clock=clock,
    )
    created = await store.create_session(
        SessionCreate(session_id="session-race-0001", nonce=b"\x0b" * 16)
    )
    assert not isinstance(created, SessionCreateDenied)
    return store, clock, created.token


def _append(token: str, key: str, index: int) -> AppendEventRequest:
    return AppendEventRequest(
        token=token,
        idempotency_key=key,
        event=store_event(index),
    )


def test_prune_cannot_replace_session_while_append_waits_on_slot() -> None:
    async def scenario() -> None:
        store, clock, token = await _created_store()
        slot_lock = store.session_lock("session-race-0001")
        outcomes: list[EventAppendAccepted | EventAppendDenied] = []

        async def append() -> None:
            outcomes.append(await store.append_event(_append(token, "idem-race-0001", 1)))

        async with anyio.create_task_group() as group, slot_lock:
            _ = group.start_soon(append)
            await anyio.wait_all_tasks_blocked()
            assert slot_lock.statistics().tasks_waiting == 1
            clock.advance_to(NOW + timedelta(minutes=15, seconds=1))
            replacement = await store.create_session(
                SessionCreate(session_id="session-race-0001", nonce=b"\x0c" * 16)
            )
            assert isinstance(replacement, SessionCreateDenied)
        assert len(outcomes) == 1
        assert isinstance(outcomes[0], EventAppendDenied)
        assert outcomes[0].code is SessionAccessCode.EXPIRED

    anyio.run(scenario)


def test_prune_defers_removal_while_access_waits_on_slot() -> None:
    async def scenario() -> None:
        store, clock, token = await _created_store()
        slot_lock = store.session_lock("session-race-0001")
        outcomes: list[SessionAccessDenied] = []

        async def access() -> None:
            result = await store.access(SessionAccess(token=token))
            assert isinstance(result, SessionAccessDenied)
            outcomes.append(result)

        async with anyio.create_task_group() as group, slot_lock:
            _ = group.start_soon(access)
            await anyio.wait_all_tasks_blocked()
            clock.advance_to(NOW + timedelta(minutes=15, seconds=1))
            assert await store.live_session_count() == 1
            late_append = await store.append_event(_append(token, "idem-expired", 6))
            late_access = await store.access(SessionAccess(token=token))
            assert isinstance(late_append, EventAppendDenied)
            assert late_append.code is SessionAccessCode.EXPIRED
            assert isinstance(late_access, SessionAccessDenied)
            assert late_access.code is SessionAccessCode.EXPIRED
        assert outcomes[0].code is SessionAccessCode.EXPIRED
        assert await store.live_session_count() == 0

    anyio.run(scenario)


def test_cancelled_append_releases_lease_before_later_prune() -> None:
    async def scenario() -> None:
        store, clock, token = await _created_store()
        slot_lock = store.session_lock("session-race-0001")
        scopes: list[anyio.CancelScope] = []

        async def append() -> None:
            with anyio.CancelScope() as scope:
                scopes.append(scope)
                _ = await store.append_event(_append(token, "idem-cancelled", 2))

        async with anyio.create_task_group() as group, slot_lock:
            _ = group.start_soon(append)
            await anyio.wait_all_tasks_blocked()
            assert store.lease_count("session-race-0001") == 1
            scopes[0].cancel()
            await anyio.wait_all_tasks_blocked()
        assert await store.live_session_count() == 1
        clock.advance_to(NOW + timedelta(minutes=15, seconds=1))
        assert await store.live_session_count() == 0

    anyio.run(scenario)


def test_expired_leased_session_counts_toward_capacity_until_release() -> None:
    async def scenario() -> None:
        store, clock, token = await _created_store()
        slot_lock = store.session_lock("session-race-0001")
        outcomes: list[SessionAccessDenied] = []

        async def access() -> None:
            result = await store.access(SessionAccess(token=token))
            assert isinstance(result, SessionAccessDenied)
            outcomes.append(result)

        async with anyio.create_task_group() as group, slot_lock:
            _ = group.start_soon(access)
            await anyio.wait_all_tasks_blocked()
            clock.advance_to(NOW + timedelta(minutes=15, seconds=1))
            assert await store.live_session_count() == 1
            for index in range(MAX_LIVE_SESSIONS - 1):
                created = await store.create_session(
                    SessionCreate(
                        session_id=f"session-future-{index:04d}",
                        nonce=(index + 100).to_bytes(16, "big"),
                    )
                )
                assert not isinstance(created, SessionCreateDenied)
            overflow = await store.create_session(
                SessionCreate(session_id="session-future-overflow", nonce=b"\xff" * 16)
            )
            assert isinstance(overflow, SessionCreateDenied)
            assert overflow.code is SessionAccessCode.SESSION_CAPACITY
        assert outcomes[0].code is SessionAccessCode.EXPIRED
        assert await store.live_session_count() == MAX_LIVE_SESSIONS - 1

    anyio.run(scenario)


def test_append_and_access_after_prune_are_denied() -> None:
    async def scenario() -> None:
        store, clock, token = await _created_store()
        clock.advance_to(NOW + timedelta(minutes=15, seconds=1))
        assert await store.live_session_count() == 0
        append = await store.append_event(_append(token, "idem-after-prune", 3))
        access = await store.access(SessionAccess(token=token))
        assert isinstance(append, EventAppendDenied)
        assert append.code is SessionAccessCode.EXPIRED
        assert isinstance(access, SessionAccessDenied)
        assert access.code is SessionAccessCode.EXPIRED

    anyio.run(scenario)


def test_different_sessions_progress_while_one_slot_is_blocked() -> None:
    async def scenario() -> None:
        store, _, _ = await _created_store()
        second = await store.create_session(
            SessionCreate(session_id="session-race-0002", nonce=b"\x0d" * 16)
        )
        assert not isinstance(second, SessionCreateDenied)
        first_lock = store.session_lock("session-race-0001")
        second_done = anyio.Event()

        async def append_second() -> None:
            result = await store.append_event(_append(second.token, "idem-second", 4))
            assert isinstance(result, EventAppendAccepted)
            second_done.set()

        async with anyio.create_task_group() as group, first_lock:
            _ = group.start_soon(append_second)
            await second_done.wait()
        access = await store.access(SessionAccess(token=second.token))
        assert isinstance(access, SessionAccessGranted)
        assert len(access.snapshot.events) == 1

    anyio.run(scenario)


def test_same_key_race_is_stable_across_100_stores() -> None:
    async def scenario() -> None:
        async def append(
            target: DemoSessionStore,
            token: str,
            outcomes: list[EventAppendAccepted | EventAppendDenied],
        ) -> None:
            outcomes.append(await target.append_event(_append(token, "idem-repeat", 5)))

        with anyio.fail_after(15):
            for repeat in range(100):
                store = DemoSessionStore(
                    signing_key=SECRET,
                    startup_epoch=f"epoch-repeat-{repeat:04d}",
                    clock=MutableClock(),
                )
                created = await store.create_session(
                    SessionCreate(
                        session_id="session-repeat",
                        nonce=repeat.to_bytes(16, "big"),
                    )
                )
                assert not isinstance(created, SessionCreateDenied)
                outcomes: list[EventAppendAccepted | EventAppendDenied] = []

                async with anyio.create_task_group() as group:
                    for _ in range(12):
                        _ = group.start_soon(append, store, created.token, outcomes)
                accepted = tuple(item for item in outcomes if isinstance(item, EventAppendAccepted))
                assert len(accepted) == 12
                assert sum(not item.replayed for item in accepted) == 1
                assert sum(item.replayed for item in accepted) == 11

    anyio.run(scenario)
