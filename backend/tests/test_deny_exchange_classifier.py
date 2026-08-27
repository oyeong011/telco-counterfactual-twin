from __future__ import annotations

import json
from urllib.parse import parse_qs

import httpx2
import pytest

from telco_twin.bootstrap import github_deny_probe

PROVIDER_RESOURCE = (
    "projects/987654321/locations/global/workloadIdentityPools/"
    "github-actions/providers/github-oidc-deny-test"
)
PROVIDER_SNAPSHOT = json.dumps(
    {
        "name": PROVIDER_RESOURCE,
        "oidc": {"issuerUri": "https://token.actions.githubusercontent.com"},
        "attributeMapping": {
            "google.subject": "assertion.sub",
            "attribute.repository": "assertion.repository",
            "attribute.repository_owner_id": "assertion.repository_owner_id",
        },
        "attributeCondition": ("assertion.repository=='oyeong011/nonmatching-preflight'"),
    },
    separators=(",", ":"),
)
CONDITION_ERROR = "The given credential is rejected by the attribute condition."


def sts_response(status_code: int, payload: bytes) -> httpx2.Response:
    """Create a complete STS wire observation."""
    request = httpx2.Request("POST", "https://sts.googleapis.com/v1/token")
    return httpx2.Response(status_code, content=payload, request=request)


def classify(
    observation: httpx2.Response | httpx2.HTTPError,
    *,
    provider_snapshot: str = PROVIDER_SNAPSHOT,
) -> github_deny_probe.DenyExchangeClassification:
    """Call the production classifier through its deny-probe facade."""
    return github_deny_probe.classify_deny_exchange(
        provider_snapshot,
        PROVIDER_RESOURCE,
        observation,
    )


@pytest.mark.parametrize("error_code", ["unauthorized_client", "invalid_grant"])
def test_documented_attribute_condition_rejection_is_proven(
    error_code: str,
) -> None:
    # Given
    response = sts_response(
        400,
        json.dumps(
            {
                "error": error_code,
                "error_description": CONDITION_ERROR,
            }
        ).encode(),
    )

    # When
    result = classify(response)

    # Then
    assert result.status == "deny-rejected"
    assert result.http_status == 400
    assert result.sts_error == error_code


@pytest.mark.parametrize(
    "transport_error",
    [
        httpx2.ConnectError("connection failed"),
        httpx2.ReadTimeout("exchange timed out"),
    ],
)
def test_transport_failure_is_rejection_unproven(
    transport_error: httpx2.HTTPError,
) -> None:
    # Given / When
    result = classify(transport_error)

    # Then
    assert result.status == "deny-exchange-rejection-unproven"
    assert result.http_status is None
    assert result.sts_error is None


def test_drifted_provider_snapshot_is_rejection_unproven() -> None:
    # Given
    drifted = PROVIDER_SNAPSHOT.replace(
        "assertion.repository=='oyeong011/nonmatching-preflight'",
        "true",
    )
    response = sts_response(
        400,
        json.dumps(
            {
                "error": "invalid_grant",
                "error_description": CONDITION_ERROR,
            }
        ).encode(),
    )

    # When
    result = classify(response, provider_snapshot=drifted)

    # Then
    assert result.status == "deny-exchange-rejection-unproven"
    assert result.provider_verified is False


@pytest.mark.parametrize(
    ("payload", "expected_error"),
    [
        (
            b'{"error":"invalid_target","error_description":"Invalid value for audience"}',
            "invalid_target",
        ),
        (
            b'{"error":"invalid_grant","error_description":"Invalid JWT Signature."}',
            "invalid_grant",
        ),
        (
            b'{"error":"permission_denied","error_description":"Permission denied"}',
            "permission_denied",
        ),
        (
            b'{"error":"unauthorized_client","error_description":"Invalid audience"}',
            "unauthorized_client",
        ),
    ],
)
def test_unrelated_sts_error_is_rejection_unproven(
    payload: bytes,
    expected_error: str,
) -> None:
    # Given / When
    result = classify(sts_response(400, payload))

    # Then
    assert result.status == "deny-exchange-rejection-unproven"
    assert result.sts_error == expected_error


def test_malformed_sts_response_is_rejection_unproven() -> None:
    # Given / When
    result = classify(sts_response(400, b"not-json"))

    # Then
    assert result.status == "deny-exchange-rejection-unproven"
    assert result.sts_error is None


def test_access_token_response_is_fatal_without_token_leak() -> None:
    # Given
    issued_credential = "fabricated-sensitive-access-value"
    response = sts_response(
        200,
        json.dumps(
            {
                "access_token": issued_credential,
                "issued_token_type": "urn:ietf:params:oauth:token-type:access_token",
                "token_type": "Bearer",
                "expires_in": 3600,
            }
        ).encode(),
    )

    # When
    result = classify(response)
    rendered = result.model_dump_json()

    # Then
    assert result.status == "deny-exchange-unexpected-success"
    assert issued_credential not in rendered


def test_production_probe_exchanges_oidc_token_without_secret_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    request_bearer = "fabricated-github-request-value"
    subject_credential = "fabricated-github-subject-value"
    monkeypatch.setenv(
        "ACTIONS_ID_TOKEN_REQUEST_URL",
        "https://token.actions.githubusercontent.test/oidc?api-version=1",
    )
    monkeypatch.setenv("ACTIONS_ID_TOKEN_REQUEST_TOKEN", request_bearer)
    requests: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(f"{request.method} {request.url}")
        if request.url.host == "token.actions.githubusercontent.test":
            assert request.headers["authorization"] == f"Bearer {request_bearer}"
            audience = request.url.params["audience"]
            assert audience == f"//iam.googleapis.com/{PROVIDER_RESOURCE}"
            content = json.dumps({"value": subject_credential}).encode()
            return httpx2.Response(200, content=content, request=request)
        assert request.url == "https://sts.googleapis.com/v1/token"
        assert "authorization" not in request.headers
        form = parse_qs(request.content.decode())
        assert form["subject_token"] == [subject_credential]
        assert form["audience"] == [f"//iam.googleapis.com/{PROVIDER_RESOURCE}"]
        content = json.dumps(
            {
                "error": "invalid_grant",
                "error_description": CONDITION_ERROR,
            }
        ).encode()
        return httpx2.Response(400, content=content, request=request)

    # When
    result = github_deny_probe.probe_deny_exchange(
        PROVIDER_SNAPSHOT,
        PROVIDER_RESOURCE,
        httpx2.MockTransport(handler),
    )
    rendered = result.model_dump_json()

    # Then
    assert result.status == "deny-rejected"
    assert len(requests) == 2
    assert request_bearer not in rendered
    assert subject_credential not in rendered


def test_production_probe_blocks_before_network_when_provider_drifted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    monkeypatch.setenv(
        "ACTIONS_ID_TOKEN_REQUEST_URL",
        "https://token.actions.githubusercontent.test/oidc?api-version=1",
    )
    monkeypatch.setenv(
        "ACTIONS_ID_TOKEN_REQUEST_TOKEN",
        "fabricated-github-request-value",
    )
    request_count = 0

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal request_count
        request_count += 1
        return httpx2.Response(500, content=b"{}", request=request)

    drifted = PROVIDER_SNAPSHOT.replace(
        "assertion.repository=='oyeong011/nonmatching-preflight'",
        "true",
    )

    # When
    result = github_deny_probe.probe_deny_exchange(
        drifted,
        PROVIDER_RESOURCE,
        httpx2.MockTransport(handler),
    )

    # Then
    assert "nonmatching-preflight" not in drifted
    assert result.status == "deny-exchange-rejection-unproven"
    assert request_count == 0
