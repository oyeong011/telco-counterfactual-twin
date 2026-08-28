"""Approval HTTP authorization, terminal evidence, expiry, and restart tests."""

import base64
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import final

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

from telco_twin.api.app import create_app
from telco_twin.api.contracts import ApprovalReadResponse
from telco_twin.api.settings import ApiSettings
from telco_twin.approval.authority_contracts import AuthorityLoadError, AuthorityMode
from telco_twin.domain.approval import (
    ApprovalProof,
    ApprovalValidationContext,
    Environment,
    RootDescriptor,
    SessionKeyCertificate,
    validate_approval_chain,
)
from telco_twin.state.demo_token import DemoTokenClaims, DemoTokenKey, encode_demo_token

from .api_test_support import bootstrap, run_approval_flow, run_to_comparison, session_headers


@final
class MutableClock:
    """Test clock whose explicit advance models trusted elapsed time."""

    def __init__(self, current: datetime) -> None:
        self.current = current

    def now(self) -> datetime:
        return self.current

    def advance(self, delta: timedelta) -> None:
        self.current += delta


def test_demo_approver_records_offline_verifiable_evidence_only_proof() -> None:
    # Given: one pending request linked to a certified demo session.
    app = create_app()
    with TestClient(app) as client:
        root = RootDescriptor.model_validate(client.get("/.well-known/approval-root").json())
        flow = run_approval_flow(client)
        pending = ApprovalReadResponse.model_validate_json(
            client.get(
                f"/api/approval-requests/{flow.approval_request_id}",
                headers=session_headers(flow.session),
            ).content
        )
        # When: the session holder records approval evidence.
        response = client.post(
            f"/api/approval-requests/{flow.approval_request_id}/approve",
            headers=session_headers(flow.session, "idem-approve-0001"),
            json={},
        )
    # Then: the proof validates offline and only advances evidence state.
    proof = ApprovalProof.model_validate(response.json()["approval_proof"])
    request = pending.approval_request
    certificate = SessionKeyCertificate.model_validate(flow.session.certificate)
    validate_approval_chain(
        proof,
        ApprovalValidationContext(
            root=root,
            certificate=certificate,
            request=request,
            environment=Environment.TEST,
            trusted_root_hashes=frozenset({root.descriptor_hash}),
            consumed_nonces=frozenset(),
            now=datetime.fromisoformat(proof.approved_at).astimezone(UTC),
        ),
    )
    assert response.status_code == 200
    assert response.json()["state"] == "approved"
    assert response.json()["effect"] == "evidence-only"
    assert "execute" not in response.text.lower()


def test_rejection_records_terminal_rejected_evidence() -> None:
    # Given: a separate pending request.
    with TestClient(create_app()) as client:
        flow = run_approval_flow(client)
        # When: the demo holder rejects it.
        response = client.post(
            f"/api/approval-requests/{flow.approval_request_id}/reject",
            headers=session_headers(flow.session, "idem-reject-0001"),
            json={},
        )
        read = client.get(
            f"/api/approval-requests/{flow.approval_request_id}",
            headers=session_headers(flow.session),
        )
    # Then: rejection is signed evidence and cannot become approved.
    assert response.status_code == 200
    assert response.json()["state"] == "rejected"
    assert response.json()["approval_proof"]["decision"] == "rejected"
    assert read.json()["state"] == "rejected"


def test_approval_requires_scoped_demo_token_and_cross_session_is_hidden() -> None:
    # Given: one pending request and an unrelated session.
    with TestClient(create_app()) as client:
        flow = run_approval_flow(client)
        other = bootstrap(client)
        # When: approval has no demo token and then another session's token.
        missing = client.post(
            f"/api/approval-requests/{flow.approval_request_id}/approve",
            headers={"Idempotency-Key": "idem-missing-approver"},
            json={},
        )
        cross_session = client.post(
            f"/api/approval-requests/{flow.approval_request_id}/approve",
            headers=session_headers(other, "idem-cross-session"),
            json={},
        )
    # Then: neither request can reach the target evidence state.
    assert missing.status_code == 401
    assert missing.json()["code"] == "approval_auth_required"
    assert cross_session.status_code == 404
    assert cross_session.json()["code"] == "approval_request_not_found"


def test_non_demo_jwt_approval_is_disabled_without_complete_configuration() -> None:
    # Given: a pending request but no issuer/audience/JWKS configuration.
    with TestClient(create_app()) as client:
        flow = run_approval_flow(client)
        # When: a bearer is offered as non-demo approver authority.
        response = client.post(
            f"/api/approval-requests/{flow.approval_request_id}/approve",
            headers={
                "Authorization": "Bearer not-a-configured-jwt",
                "Idempotency-Key": "idem-jwt-disabled",
            },
            json={},
        )
    # Then: non-demo approval is explicitly unavailable, never inferred.
    assert response.status_code == 503
    assert response.json()["code"] == "jwt_approver_disabled"


def test_expired_token_is_401_and_restart_epoch_is_410() -> None:
    # Given: one token under a stable secret and original startup epoch.
    clock = MutableClock(datetime(2026, 8, 28, 0, 0, 0, tzinfo=UTC))
    first_app = create_app(clock=clock)
    with TestClient(first_app) as first_client:
        session = bootstrap(first_client)
        clock.advance(timedelta(minutes=15, seconds=1))
        # When: the original process resolves an expired token.
        expired = first_client.get("/api/scenarios", headers=session_headers(session))
    restarted_app = create_app(clock=MutableClock(datetime(2026, 8, 28, tzinfo=UTC)))
    with TestClient(restarted_app) as restarted_client:
        # When: a new startup epoch resolves the still-authentic original token.
        lost = restarted_client.get("/api/scenarios", headers=session_headers(session))
    # Then: expiration and restart remain distinguishable HTTP semantics.
    assert expired.status_code == 401
    assert expired.json()["code"] == "demo_token_expired"
    assert lost.status_code == 410
    assert lost.json()["code"] == "demo_session_lost"


def test_current_epoch_authentic_token_for_absent_session_is_404() -> None:
    # Given: authentic current-epoch claims naming no retained session slot.
    clock = MutableClock(datetime(2026, 8, 28, 0, 0, 0, tzinfo=UTC))
    settings = ApiSettings()
    app = create_app(settings=settings, clock=clock)
    claims = DemoTokenClaims(
        v=1,
        session_id="session-absent",
        startup_epoch=app.runtime.startup_epoch,
        issued_at="2026-08-28T00:00:00Z",
        expires_at="2026-08-28T00:15:00Z",
        nonce="AgICAgICAgICAgICAgICAg",
    )
    token = encode_demo_token(
        DemoTokenKey(settings.demo_token_signing_secret.get_secret_value().encode()),
        claims,
    )
    with TestClient(app) as client:
        # When: the authenticated token resolves its absent live slot.
        response = client.get(
            "/api/scenarios",
            headers={"X-Demo-Session-Token": token},
        )
    # Then: absence remains distinct from invalid, expired, and restart semantics.
    assert response.status_code == 404
    assert response.json()["code"] == "demo_session_not_found"


def test_stale_observation_blocks_approval_request_with_structured_error() -> None:
    # Given: a simulated comparison whose observation ages beyond policy bounds.
    clock = MutableClock(datetime(2026, 8, 28, 0, 0, 0, tzinfo=UTC))
    with TestClient(create_app(clock=clock)) as client:
        flow = run_to_comparison(client)
        clock.advance(timedelta(minutes=5))
        # When: approval admission re-evaluates current observation freshness.
        response = client.post(
            f"/api/simulations/{flow.simulation_id}/approval-requests",
            headers=session_headers(flow.session, "idem-stale-approval"),
            json={},
        )
    # Then: stale evidence cannot create pending state.
    assert response.status_code == 422
    assert response.json()["code"] == "policy_ineligible"


def test_expired_approval_window_returns_structured_conflict_before_append() -> None:
    # Given: a pending request whose exact 60-second evidence window has elapsed.
    clock = MutableClock(datetime(2026, 8, 28, 0, 0, 0, tzinfo=UTC))
    with TestClient(create_app(clock=clock)) as client:
        flow = run_approval_flow(client)
        clock.advance(timedelta(seconds=61))
        # When: the session holder attempts a late approval.
        response = client.post(
            f"/api/approval-requests/{flow.approval_request_id}/approve",
            headers=session_headers(flow.session, "idem-late-approval"),
            json={},
        )
    # Then: expiry is a stable problem and no terminal state is appended.
    assert response.status_code == 409
    assert response.json()["code"] == "approval_window_expired"


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def test_configured_eddsa_jwt_with_approver_role_can_record_evidence() -> None:
    # Given: complete issuer/audience/JWKS config and a signed approver JWT.
    signing_key = Ed25519PrivateKey.generate()
    public = signing_key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    settings = ApiSettings(
        jwt_issuer="https://issuer.example",
        jwt_audience="telco-twin-api",
        jwt_jwks_json=json.dumps(
            {
                "keys": [
                    {
                        "alg": "EdDSA",
                        "crv": "Ed25519",
                        "kid": "approver-key-1",
                        "kty": "OKP",
                        "use": "sig",
                        "x": _base64url(public),
                    }
                ]
            }
        ),
    )
    now = datetime.now(UTC)
    bearer = jwt.encode(
        {
            "aud": "telco-twin-api",
            "exp": int((now + timedelta(minutes=2)).timestamp()),
            "iat": int(now.timestamp()),
            "iss": "https://issuer.example",
            "roles": ["approver"],
            "sub": "synthetic-approver",
        },
        signing_key,
        algorithm="EdDSA",
        headers={"kid": "approver-key-1"},
    )
    with TestClient(create_app(settings=settings)) as client:
        flow = run_approval_flow(client)
        # When: approval is recorded without a demo bearer.
        response = client.post(
            f"/api/approval-requests/{flow.approval_request_id}/approve",
            headers={
                "Authorization": f"Bearer {bearer}",
                "Idempotency-Key": "idem-jwt-approve",
            },
            json={},
        )
    # Then: only the configured role-bearing JWT path succeeds.
    assert response.status_code == 200
    assert response.json()["state"] == "approved"


def test_partial_jwt_config_and_production_test_root_fail_at_startup() -> None:
    # Given/When: JWT config is partial.
    with pytest.raises(ValidationError):
        _ = ApiSettings(jwt_issuer="https://issuer.example")
    root_json = (
        Path(__file__).parents[1] / "fixtures/approval/test-root-descriptor.json"
    ).read_text()
    production_material = "production-demo-material-without-fixture-word-1234"
    production = ApiSettings(
        environment=AuthorityMode.PRODUCTION,
        approval_root_descriptor_json=root_json,
        demo_token_signing_secret=SecretStr(production_material),
        deployed_image_digest=f"sha256:{'1' * 64}",
        expected_image_digest=f"sha256:{'1' * 64}",
    )
    # When/Then: production refuses the known test root before serving routes.
    with pytest.raises(AuthorityLoadError):
        _ = create_app(settings=production)
