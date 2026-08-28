"""Approval-root discovery and bounded bootstrap HTTP tests."""

import logging

import pytest
from fastapi.testclient import TestClient
from nacl.signing import VerifyKey

from telco_twin.api.app import create_app
from telco_twin.api.contracts import DemoSessionResponse
from telco_twin.domain.approval import (
    RootDescriptor,
    SessionKeyCertificate,
    certificate_signing_bytes,
    decode_base64url,
)

from .api_test_support import ALLOWED_ORIGIN, bootstrap


def test_bootstrap_returns_only_opaque_token_and_root_signed_public_certificate() -> None:
    # Given: the public root descriptor.
    with TestClient(create_app()) as client:
        root_response = client.get("/.well-known/approval-root")
        # When: a synthetic-only session is bootstrapped.
        session = bootstrap(client)
    # Then: the certificate verifies offline and no private material is represented.
    root = RootDescriptor.model_validate(root_response.json())
    certificate = SessionKeyCertificate.model_validate(session.certificate)
    _ = VerifyKey(decode_base64url(root.public_key_jwk.x)).verify(
        certificate_signing_bytes(certificate),
        decode_base64url(certificate.certificate_signature),
    )
    assert certificate.session_id == session.session_id
    assert certificate.root_key_id == root.root_key_id
    public_text = f"{root_response.text}{session.certificate}".lower()
    assert all(term not in public_text for term in ("private", "signing_key", "secret"))


def test_bootstrap_requires_allowed_origin_and_rejects_body_over_eight_kib() -> None:
    # Given: one fresh application.
    with TestClient(create_app()) as client:
        # When: origin is missing, foreign, and an allowed request is oversized.
        missing = client.post("/api/demo-sessions", json={"synthetic_only": True})
        foreign = client.post(
            "/api/demo-sessions",
            headers={"Origin": "https://foreign.invalid"},
            json={"synthetic_only": True},
        )
        oversized = client.post(
            "/api/demo-sessions",
            headers={"Origin": ALLOWED_ORIGIN, "Content-Type": "application/json"},
            content=b"{" + b'"padding":"' + (b"x" * 8192) + b'"}',
        )
    # Then: origin is fail-closed and body bytes are bounded before parsing.
    assert missing.status_code == 403
    assert missing.json()["code"] == "origin_required"
    assert foreign.status_code == 403
    assert foreign.json()["code"] == "origin_forbidden"
    assert oversized.status_code == 413
    assert oversized.json()["code"] == "bootstrap_body_too_large"


def test_bootstrap_enforces_five_per_minute_with_burst_ten_by_client_ip() -> None:
    # Given: one IP with a full ten-request burst allowance.
    with TestClient(create_app()) as client:
        accepted = [
            client.post(
                "/api/demo-sessions",
                headers={"Origin": ALLOWED_ORIGIN},
                json={"synthetic_only": True},
            )
            for _ in range(10)
        ]
        # When: the same IP exceeds the burst without refill time.
        limited = client.post(
            "/api/demo-sessions",
            headers={"Origin": ALLOWED_ORIGIN},
            json={"synthetic_only": True},
        )
    # Then: ten are accepted and the next response carries retry guidance.
    assert all(response.status_code == 201 for response in accepted)
    assert limited.status_code == 429
    assert limited.json()["code"] == "bootstrap_rate_limited"
    assert int(limited.headers["Retry-After"]) >= 1


def test_bootstrap_never_logs_opaque_token_or_accepts_headers_as_authority(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Given: invalid authority-looking headers on the unauthenticated bootstrap.
    logging.getLogger("telco_twin.api").setLevel(logging.INFO)
    with (
        caplog.at_level(logging.INFO, logger="telco_twin.api"),
        TestClient(create_app()) as client,
    ):
        # When: bootstrap receives headers that have no authority on this route.
        response = client.post(
            "/api/demo-sessions",
            headers={
                "Origin": ALLOWED_ORIGIN,
                "Authorization": "Bearer ignored-bootstrap-value",
                "X-Demo-Session-Token": "ignored-demo-value",
                "Idempotency-Key": "ignored-idempotency-value",
            },
            json={"synthetic_only": True},
        )
    # Then: it succeeds solely from origin/body/rate rules and logs no bearer value.
    assert response.status_code == 201
    token = DemoSessionResponse.model_validate_json(response.content).demo_token
    assert token not in caplog.text
    assert "ignored-bootstrap-value" not in caplog.text
    assert "ignored-demo-value" not in caplog.text
