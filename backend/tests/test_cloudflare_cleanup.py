from __future__ import annotations

from typing import TYPE_CHECKING

import httpx2
import pytest

from telco_twin.bootstrap.cloudflare_probe import (
    CloudflareContext,
    CloudflareTransports,
    probe_cloudflare,
)
from telco_twin.bootstrap.probe_errors import ProviderProbeError

CLOUDFLARE_CREDENTIAL = "fabricated-cloudflare-token"

if TYPE_CHECKING:
    from collections.abc import Callable

CONTEXT = CloudflareContext(
    account_id="account-id",
    api_token=CLOUDFLARE_CREDENTIAL,
    source_sha="d" * 40,
    wrangler_command="unused-wrangler",
)


def create_handler(
    create_payload: bytes,
    delete_status: int,
    requests: list[str],
) -> Callable[[httpx2.Request], httpx2.Response]:
    """Build a wire fake for create-contract and cleanup behavior."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        path = request.url.path
        requests.append(f"{request.method} {path}")
        if path.endswith("/user/tokens/verify"):
            content = b'{"success":true,"result":{"id":"token-id","status":"active"}}'
            return httpx2.Response(200, content=content, request=request)
        if path.endswith("/accounts/account-id"):
            content = b'{"success":true,"result":{"id":"account-id"}}'
            return httpx2.Response(200, content=content, request=request)
        if path.endswith("/pages/projects") and request.method == "GET":
            return httpx2.Response(
                200,
                content=b'{"success":true,"result":[]}',
                request=request,
            )
        if path.endswith("/pages/projects") and request.method == "POST":
            return httpx2.Response(201, content=create_payload, request=request)
        if request.method == "DELETE":
            content = b'{"success":true,"result":null}'
            return httpx2.Response(delete_status, content=content, request=request)
        return httpx2.Response(404, content=b"{}", request=request)

    return handler


@pytest.mark.parametrize(
    ("create_payload", "expected_cleanup_name"),
    [
        (b'{"success":true,"result":{}}', "twin-preflight-test"),
        (
            b'{"success":true,"result":{"id":"project-id","name":"twin-preflight-returned"}}',
            "twin-preflight-test",
        ),
        (
            b'{"success":true,"result":{"id":"project-id","name":"unrelated-project"}}',
            "twin-preflight-test",
        ),
    ],
)
def test_successful_create_contract_failure_still_deletes_safe_identity(
    create_payload: bytes,
    expected_cleanup_name: str,
) -> None:
    # Given
    requests: list[str] = []
    handler = create_handler(create_payload, 200, requests)
    transports = CloudflareTransports(
        api=httpx2.MockTransport(handler),
        public=httpx2.MockTransport(handler),
    )

    # When
    with pytest.raises(ProviderProbeError):
        _ = probe_cloudflare(CONTEXT, transports, suffix="test")

    # Then
    deletes = tuple(request for request in requests if request.startswith("DELETE "))
    expected = f"DELETE /client/v4/accounts/account-id/pages/projects/{expected_cleanup_name}"
    assert deletes == (expected,)
    assert all("unrelated-project" not in request for request in deletes)


def test_cleanup_failure_after_invalid_successful_create_is_fatal() -> None:
    # Given
    requests: list[str] = []
    handler = create_handler(b'{"success":true,"result":{}}', 500, requests)
    transports = CloudflareTransports(
        api=httpx2.MockTransport(handler),
        public=httpx2.MockTransport(handler),
    )

    # When / Then
    with pytest.raises(ProviderProbeError, match="cloudflare-cleanup-failed"):
        _ = probe_cloudflare(CONTEXT, transports, suffix="test")
    assert any(request.startswith("DELETE ") for request in requests)
