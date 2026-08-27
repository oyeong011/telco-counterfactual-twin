from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

import httpx2
import pytest

from telco_twin.bootstrap.gcp_commands import GcpContext
from telco_twin.bootstrap.gcp_iam_probe import probe_gcp_iam
from telco_twin.bootstrap.preflight_contract import (
    GCP_BILLING_PERMISSIONS,
    GCP_PROJECT_PERMISSIONS,
)
from telco_twin.bootstrap.probe_errors import ProviderProbeError

if TYPE_CHECKING:
    from pathlib import Path


def install_fake_token_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    succeeds: bool,
) -> None:
    """Install a fake gcloud access-token command without exposing a real credential."""
    tool_dir = tmp_path / "bin"
    tool_dir.mkdir()
    gcloud = tool_dir / "gcloud"
    exit_code = 0 if succeeds else 1
    _ = gcloud.write_text(
        f"#!/bin/sh\nprintf '%s\\n' 'fabricated-access-token-value'\nexit {exit_code}\n",
        encoding="utf-8",
    )
    gcloud.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tool_dir}:{os.environ['PATH']}")


def context() -> GcpContext:
    """Return stable non-secret GCP identifiers for wire tests."""
    return GcpContext(
        project_id="example-project",
        project_number="987654321",
        billing_account_id="ABC-123",
        owner_id="12345678",
    )


def test_iam_probe_posts_every_exact_project_and_billing_permission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    install_fake_token_command(tmp_path, monkeypatch, succeeds=True)
    seen_urls: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen_urls.append(str(request.url))
        assert request.method == "POST"
        assert request.headers["authorization"] == "Bearer fabricated-access-token-value"
        if "cloudresourcemanager" in request.url.host:
            for permission in GCP_PROJECT_PERMISSIONS:
                assert permission.encode() in request.content
            payload = {"permissions": list(GCP_PROJECT_PERMISSIONS)}
        else:
            for permission in GCP_BILLING_PERMISSIONS:
                assert permission.encode() in request.content
            payload = {"permissions": list(GCP_BILLING_PERMISSIONS)}
        return httpx2.Response(200, content=json.dumps(payload).encode(), request=request)

    # When
    receipt = probe_gcp_iam(context(), httpx2.MockTransport(handler))

    # Then
    assert receipt.project_permissions == GCP_PROJECT_PERMISSIONS
    assert receipt.billing_permissions == GCP_BILLING_PERMISSIONS
    assert "fabricated-access-token-value" not in receipt.model_dump_json()
    assert seen_urls == [
        "https://cloudresourcemanager.googleapis.com/v1/projects/example-project:testIamPermissions",
        "https://cloudbilling.googleapis.com/v1/billingAccounts/ABC-123:testIamPermissions",
    ]


def test_iam_probe_rejects_http_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    install_fake_token_command(tmp_path, monkeypatch, succeeds=True)

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(403, content=b"{}", request=request)

    # When / Then
    with pytest.raises(ProviderProbeError, match="gcp-project-permissions-http-403"):
        _ = probe_gcp_iam(context(), httpx2.MockTransport(handler))


def test_iam_probe_rejects_access_token_command_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    install_fake_token_command(tmp_path, monkeypatch, succeeds=False)

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, content=b'{"permissions":[]}', request=request)

    # When / Then
    with pytest.raises(ProviderProbeError, match="gcloud-access-token-failed"):
        _ = probe_gcp_iam(context(), httpx2.MockTransport(handler))
