from __future__ import annotations

import httpx2
import pytest

from telco_twin.bootstrap.neon_probe import NeonContext, probe_neon
from telco_twin.bootstrap.probe_errors import ProviderProbeError


def test_neon_probe_gets_exact_organization_and_projects_without_mutation() -> None:
    # Given
    requests: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(f"{request.method} {request.url}")
        assert request.method == "GET"
        assert request.headers["authorization"] == "Bearer fabricated-neon-api-key"
        if request.url.path.endswith("/organizations/org-test"):
            content = b'{"id":"org-test","name":"Test"}'
        else:
            content = b'{"projects":[{"id":"project-one"}]}'
        return httpx2.Response(200, content=content, request=request)

    # When
    receipt = probe_neon(
        NeonContext(org_id="org-test", api_key="fabricated-neon-api-key"),
        httpx2.MockTransport(handler),
    )

    # Then
    assert receipt.org_id == "org-test"
    assert receipt.project_count == 1
    assert "fabricated-neon-api-key" not in receipt.model_dump_json()
    assert requests == [
        "GET https://console.neon.tech/api/v2/organizations/org-test",
        "GET https://console.neon.tech/api/v2/projects?org_id=org-test&limit=1",
    ]


def test_neon_probe_rejects_projects_http_failure() -> None:
    # Given
    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("/organizations/org-test"):
            return httpx2.Response(
                200,
                content=b'{"id":"org-test"}',
                request=request,
            )
        return httpx2.Response(403, content=b"{}", request=request)

    # When / Then
    with pytest.raises(ProviderProbeError, match="neon-projects-http-403"):
        _ = probe_neon(
            NeonContext(org_id="org-test", api_key="fabricated-neon-api-key"),
            httpx2.MockTransport(handler),
        )
