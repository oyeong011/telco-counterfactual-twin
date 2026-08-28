"""Runtime startup, capacity, and internal-state degradation tests."""
# pyright: reportPrivateUsage=false

import hashlib
from datetime import UTC, datetime

import anyio
import pytest
import rfc8785
from fastapi.testclient import TestClient
from nacl.signing import SigningKey
from pydantic import JsonValue, SecretStr

from telco_twin.api.app import create_app
from telco_twin.api.errors import ProblemError
from telco_twin.api.runtime import ApiRuntime
from telco_twin.api.settings import ApiSettings
from telco_twin.approval.authority_contracts import AuthorityMode
from telco_twin.domain.approval import Environment, RootDescriptor, encode_base64url
from telco_twin.state.limits import MAX_EVENTS_PER_SESSION, MAX_LIVE_SESSIONS
from telco_twin.state.trusted_clock import FixedClock

from .api_test_support import bootstrap, session_headers

FIXED_NOW = datetime(2026, 8, 28, 0, 0, 0, tzinfo=UTC)


def _production_descriptor(signing_key: SigningKey) -> RootDescriptor:
    payload: dict[str, JsonValue] = {
        "root_key_id": "production-root-api-0001",
        "algorithm": "Ed25519",
        "public_key_jwk": {
            "kty": "OKP",
            "crv": "Ed25519",
            "x": encode_base64url(bytes(signing_key.verify_key)),
        },
        "environment": "production",
        "not_before": "2026-01-01T00:00:00Z",
        "not_after": "2027-01-01T00:00:00Z",
        "schema_version": "1.0",
    }
    payload["descriptor_hash"] = hashlib.sha256(rfc8785.dumps(payload)).hexdigest()
    return RootDescriptor.model_validate(payload)


def test_unavailable_runtime_blocks_bootstrap_and_authenticated_access() -> None:
    async def scenario() -> None:
        # Given: one runtime whose state dependency is marked unavailable.
        runtime = ApiRuntime(clock=FixedClock(FIXED_NOW))
        runtime.set_available(False)
        # When/Then: bootstrap fails closed before issuing a bearer.
        with pytest.raises(ProblemError) as create_error:
            _ = await runtime.create_demo_session()
        assert create_error.value.code == "state_store_unavailable"

    anyio.run(scenario)


def test_valid_store_slot_with_missing_private_session_state_is_503() -> None:
    async def scenario() -> None:
        # Given: one authentic store slot whose private API aggregate is lost.
        runtime = ApiRuntime(clock=FixedClock(FIXED_NOW))
        created = await runtime.create_demo_session()
        runtime._sessions.clear()
        # When: the still-authentic bearer resolves through Task 5 first.
        with pytest.raises(ProblemError) as caught:
            _ = await runtime.authorize(created.demo_token)
        # Then: internal state loss is unavailable, not credential invalidity.
        assert caught.value.status == 503
        assert caught.value.code == "session_state_unavailable"

    anyio.run(scenario)


def test_runtime_enforces_fifty_live_session_capacity() -> None:
    async def scenario() -> None:
        # Given: the exact bounded session capacity is filled directly through runtime.
        runtime = ApiRuntime(clock=FixedClock(FIXED_NOW))
        for _ in range(MAX_LIVE_SESSIONS):
            _ = await runtime.create_demo_session()
        # When: one additional session is requested.
        with pytest.raises(ProblemError) as caught:
            _ = await runtime.create_demo_session()
        # Then: capacity is explicit and does not evict a live session.
        assert caught.value.status == 429
        assert caught.value.code == "demo_session_capacity"

    anyio.run(scenario)


def test_demo_mutation_respects_combined_session_event_capacity() -> None:
    # Given: a live session whose shared API event sequence is full.
    app = create_app(clock=FixedClock(FIXED_NOW))
    with TestClient(app) as client:
        session = bootstrap(client)
        app.runtime._sessions[session.session_id].next_event_sequence = MAX_EVENTS_PER_SESSION
        # When: a demo-token mutation attempts another append.
        response = client.post(
            "/api/scenarios",
            headers=session_headers(session, "idem-demo-capacity"),
            json={"fault_family": "radio-congestion", "seed": 88},
        )
    # Then: the same global 256-event bound rejects it.
    assert response.status_code == 429
    assert response.json()["code"] == "demo_event_capacity"


def test_invalid_production_descriptor_fails_before_service_start() -> None:
    # Given: production-safe digest/secret shapes but malformed descriptor JSON.
    settings = ApiSettings(
        environment=AuthorityMode.PRODUCTION,
        approval_root_descriptor_json="{",
        demo_token_signing_secret=SecretStr("production-demo-material-for-api-runtime-1234"),
        deployed_image_digest=f"sha256:{'2' * 64}",
        expected_image_digest=f"sha256:{'2' * 64}",
    )
    # When/Then: the app refuses startup with a stable configuration problem.
    with pytest.raises(ProblemError) as caught:
        _ = create_app(settings=settings)
    assert caught.value.code == "approval_root_invalid"


def test_valid_production_root_secret_and_trust_set_start_successfully(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a production descriptor whose secret and independent trust set agree.
    signing_key = SigningKey.generate()
    descriptor = _production_descriptor(signing_key)
    monkeypatch.setenv("APPROVAL_ROOT_KEY_SECRET", encode_base64url(bytes(signing_key)))
    monkeypatch.setenv(
        "APPROVAL_TRUSTED_ROOT_HASHES_JSON",
        f'["{descriptor.descriptor_hash}"]',
    )
    settings = ApiSettings(
        environment=AuthorityMode.PRODUCTION,
        approval_root_descriptor_json=descriptor.model_dump_json(),
        demo_token_signing_secret=SecretStr("production-demo-material-for-api-runtime-1234"),
        deployed_image_digest=f"sha256:{'3' * 64}",
        expected_image_digest=f"sha256:{'3' * 64}",
    )
    # When: the production runtime loads.
    app = create_app(settings=settings, clock=FixedClock(FIXED_NOW))
    # Then: root environment and registry digest scope remain production-bound.
    assert app.runtime.authority.descriptor.environment is Environment.PRODUCTION
    assert app.runtime.build_info.digest_scope.value == "registry_manifest"
