"""Authenticated atomic append boundary regressions."""

from datetime import timedelta

import anyio

from telco_twin.state.store_models import (
    AppendEventRequest,
    EventAppendDenied,
    SessionAccessCode,
    SessionCreate,
    SessionCreateDenied,
)

from .test_memory_store import (
    NOW,
    MutableClock,
    created_session,
    demo_store,
    store_event,
)


def _request(token: str) -> AppendEventRequest:
    return AppendEventRequest(
        token=token,
        idempotency_key="idem-authenticated",
        event=store_event(1),
    )


def test_invalid_token_cannot_append_event() -> None:
    async def scenario() -> None:
        store = demo_store()
        _ = await created_session(store)
        result = await store.append_event(_request("malformed"))
        assert isinstance(result, EventAppendDenied)
        assert result.code is SessionAccessCode.INVALID

    anyio.run(scenario)


def test_expired_token_cannot_append_without_prior_time_advancing_operation() -> None:
    async def scenario() -> None:
        clock = MutableClock()
        store = demo_store(clock=clock)
        created = await created_session(store)
        clock.advance_to(NOW + timedelta(minutes=15, seconds=1))
        result = await store.append_event(_request(created.token))
        assert isinstance(result, EventAppendDenied)
        assert result.code is SessionAccessCode.EXPIRED

    anyio.run(scenario)


def test_cross_epoch_token_cannot_append_event() -> None:
    async def scenario() -> None:
        first = demo_store("epoch-auth-first")
        created = await created_session(first)
        restarted = demo_store("epoch-auth-second")
        result = await restarted.append_event(_request(created.token))
        assert isinstance(result, EventAppendDenied)
        assert result.code is SessionAccessCode.LOST

    anyio.run(scenario)


def test_valid_token_for_absent_session_cannot_append_to_other_session() -> None:
    async def scenario() -> None:
        issuer = demo_store("epoch-auth-shared")
        created = await created_session(issuer)
        other = demo_store("epoch-auth-shared")
        other_created = await other.create_session(
            SessionCreate(session_id="session-other", nonce=b"\x09" * 16)
        )
        assert not isinstance(other_created, SessionCreateDenied)
        result = await other.append_event(_request(created.token))
        assert isinstance(result, EventAppendDenied)
        assert result.code is SessionAccessCode.NOT_FOUND

    anyio.run(scenario)


def test_append_request_carries_no_session_body_hash_or_time() -> None:
    fields = frozenset(AppendEventRequest.__dataclass_fields__)
    assert fields == {"token", "idempotency_key", "event"}
