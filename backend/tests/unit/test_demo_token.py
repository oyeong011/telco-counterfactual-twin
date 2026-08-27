"""Exact demo token and restart-semantics tests."""

import base64
import hashlib
import hmac
from datetime import UTC, datetime, timedelta
from typing import Final

import anyio
from pydantic import JsonValue, TypeAdapter

from telco_twin.domain.canonical import canonical_json_bytes
from telco_twin.state.demo_token import DemoTokenClaims, DemoTokenKey, encode_demo_token
from telco_twin.state.memory_store import DemoSessionStore
from telco_twin.state.store_models import (
    SessionAccess,
    SessionAccessCode,
    SessionAccessDenied,
    SessionAccessGranted,
    SessionCreate,
    SessionCreateDenied,
)

NOW = datetime(2026, 8, 27, 0, 0, 0, tzinfo=UTC)
SECRET_BYTES = b"demo-token-test-key-material-32b"
JSON_ADAPTER: Final[TypeAdapter[JsonValue]] = TypeAdapter(JsonValue)


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + ("=" * (-len(value) % 4)))


def test_demo_token_matches_independent_rfc8785_hmac_contract() -> None:
    # Given: exact claims, startup epoch, and a distinct demo HMAC key.
    claims = DemoTokenClaims(
        v=1,
        session_id="session-0001",
        startup_epoch="epoch-0001",
        issued_at="2026-08-27T00:00:00Z",
        expires_at="2026-08-27T00:15:00Z",
        nonce="AAECAwQFBgcICQoLDA0ODw",
    )
    # When: the production encoder creates the opaque token.
    token = encode_demo_token(DemoTokenKey(SECRET_BYTES), claims)
    payload_text, signature_text = token.split(".")
    payload = _decode(payload_text)
    expected_payload = canonical_json_bytes(
        JSON_ADAPTER.validate_python(claims.model_dump(mode="json"))
    )
    expected_signature = hmac.new(
        SECRET_BYTES,
        b"telco-twin/demo-token/v1\0" + expected_payload,
        hashlib.sha256,
    ).digest()
    # Then: both base64url components match the independent formula exactly.
    assert payload == expected_payload
    assert _decode(signature_text) == expected_signature
    assert "=" not in token


def test_restart_epoch_invalid_and_expired_tokens_have_distinct_domain_semantics() -> None:
    async def scenario() -> None:
        # Given: a token issued by one startup epoch.
        first = DemoSessionStore(
            signing_key=DemoTokenKey(SECRET_BYTES),
            startup_epoch="epoch-0001",
        )
        created = await first.create_session(
            SessionCreate(session_id="session-0001", now=NOW, nonce=b"\x01" * 16)
        )
        assert not isinstance(created, SessionCreateDenied)
        restarted = DemoSessionStore(
            signing_key=DemoTokenKey(SECRET_BYTES),
            startup_epoch="epoch-0002",
        )
        # When: restart, forgery, and expiry paths resolve the token.
        lost = await restarted.access(SessionAccess(token=created.token, now=NOW))
        forged = await first.access(
            SessionAccess(
                token=created.token[:-1] + ("A" if created.token[-1] != "A" else "B"), now=NOW
            )
        )
        expired = await first.access(
            SessionAccess(token=created.token, now=NOW + timedelta(minutes=15, seconds=1))
        )
        # Then: 410 restart is distinguishable from both 401 paths.
        assert isinstance(lost, SessionAccessDenied)
        assert lost.code is SessionAccessCode.LOST
        assert lost.http_status == 410
        assert isinstance(forged, SessionAccessDenied)
        assert forged.code is SessionAccessCode.INVALID
        assert forged.http_status == 401
        assert isinstance(expired, SessionAccessDenied)
        assert expired.code is SessionAccessCode.EXPIRED
        assert expired.http_status == 401

    anyio.run(scenario)


def test_current_epoch_valid_token_for_absent_session_is_404_semantic() -> None:
    async def scenario() -> None:
        # Given: a valid token minted for the current epoch but no stored session.
        store = DemoSessionStore(
            signing_key=DemoTokenKey(SECRET_BYTES),
            startup_epoch="epoch-0001",
        )
        claims = DemoTokenClaims(
            v=1,
            session_id="session-absent",
            startup_epoch="epoch-0001",
            issued_at="2026-08-27T00:00:00Z",
            expires_at="2026-08-27T00:15:00Z",
            nonce="AgICAgICAgICAgICAgICAg",
        )
        token = encode_demo_token(DemoTokenKey(SECRET_BYTES), claims)
        # When: the current-epoch token is resolved.
        result = await store.access(SessionAccess(token=token, now=NOW))
        # Then: the domain returns the later-API 404 mapping code.
        assert isinstance(result, SessionAccessDenied)
        assert result.code is SessionAccessCode.NOT_FOUND
        assert result.http_status == 404

    anyio.run(scenario)


def test_malformed_and_future_tokens_are_401_semantics() -> None:
    async def scenario() -> None:
        # Given: one live token and a current-epoch store.
        store = DemoSessionStore(
            signing_key=DemoTokenKey(SECRET_BYTES),
            startup_epoch="epoch-0001",
        )
        created = await store.create_session(
            SessionCreate(session_id="session-0001", now=NOW, nonce=b"\x03" * 16)
        )
        assert not isinstance(created, SessionCreateDenied)
        # When: malformed bytes and a pre-issuance assessment instant are used.
        malformed_value = chr(33)
        malformed = await store.access(SessionAccess(token=malformed_value, now=NOW))
        future = await store.access(
            SessionAccess(token=created.token, now=NOW - timedelta(seconds=1))
        )
        # Then: neither path is confused with restart or live-state absence.
        assert isinstance(malformed, SessionAccessDenied)
        assert malformed.code is SessionAccessCode.INVALID
        assert malformed.http_status == 401
        assert isinstance(future, SessionAccessDenied)
        assert future.code is SessionAccessCode.INVALID
        assert future.http_status == 401

    anyio.run(scenario)


def test_store_never_persists_token_or_displays_hmac_key() -> None:
    async def scenario() -> None:
        # Given: a newly issued opaque token.
        store = DemoSessionStore(
            signing_key=DemoTokenKey(SECRET_BYTES),
            startup_epoch="epoch-0001",
        )
        created = await store.create_session(
            SessionCreate(session_id="session-0001", now=NOW, nonce=b"\x04" * 16)
        )
        assert not isinstance(created, SessionCreateDenied)
        # When: public store and live snapshot representations are inspected.
        access = await store.access(SessionAccess(token=created.token, now=NOW))
        # Then: the token and HMAC key occur in neither persisted evidence representation.
        assert created.token not in repr(store)
        assert SECRET_BYTES.hex() not in repr(store)
        assert isinstance(access, SessionAccessGranted)
        assert "token" not in access.snapshot.__dataclass_fields__

    anyio.run(scenario)
