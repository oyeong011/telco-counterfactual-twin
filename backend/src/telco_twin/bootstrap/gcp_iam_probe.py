"""Typed GCP project and billing-account IAM capability probes."""

from __future__ import annotations

from typing import ClassVar

import httpx2
from pydantic import BaseModel, ConfigDict, Field

from telco_twin.bootstrap.gcp_commands import GcpContext, run_command
from telco_twin.bootstrap.http_client import create_http_client
from telco_twin.bootstrap.preflight_contract import (
    GCP_BILLING_PERMISSIONS,
    GCP_PROJECT_PERMISSIONS,
    receipt_for,
)
from telco_twin.bootstrap.probe_errors import ProviderProbeError

HTTP_OK = 200


class TestPermissionsResponse(BaseModel):
    """Google IAM testIamPermissions response boundary."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)

    permissions: tuple[str, ...] = ()


class GcpIamReceipt(BaseModel):
    """Permission subsets proven by the project and billing IAM APIs."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    project_permissions: tuple[str, ...]
    billing_permissions: tuple[str, ...]
    project_status: int = Field(ge=100, le=599)
    billing_status: int = Field(ge=100, le=599)
    evidence: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


def _ordered_subset(expected: tuple[str, ...], returned: tuple[str, ...]) -> tuple[str, ...]:
    granted = frozenset(returned)
    return tuple(permission for permission in expected if permission in granted)


def _parse_permissions(response: httpx2.Response, scope: str) -> TestPermissionsResponse:
    if response.status_code != HTTP_OK:
        code = f"gcp-{scope}-permissions-http-{response.status_code}"
        raise ProviderProbeError(code)
    try:
        return TestPermissionsResponse.model_validate_json(response.content)
    except ValueError:
        code = f"gcp-{scope}-permissions-invalid-json"
        raise ProviderProbeError(code) from None


def probe_gcp_iam(
    context: GcpContext,
    transport: httpx2.BaseTransport | None = None,
) -> GcpIamReceipt:
    """Test every exact Task 1 permission without printing the access token."""
    token_result = run_command(("gcloud", "auth", "print-access-token"))
    token = token_result.stdout.strip()
    if token_result.returncode != 0 or not token:
        code = "gcloud-access-token-failed"
        raise ProviderProbeError(code)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        with create_http_client(
            "https://cloudresourcemanager.googleapis.com",
            headers,
            transport,
        ) as client:
            project_response = client.post(
                f"/v1/projects/{context.project_id}:testIamPermissions",
                json={"permissions": list(GCP_PROJECT_PERMISSIONS)},
            )
            billing_base = "https://cloudbilling.googleapis.com/v1/billingAccounts"
            billing_url = f"{billing_base}/{context.billing_account_id}:testIamPermissions"
            billing_response = client.post(
                billing_url,
                json={"permissions": list(GCP_BILLING_PERMISSIONS)},
            )
    except httpx2.HTTPError:
        code = "gcp-permissions-network-failed"
        raise ProviderProbeError(code) from None
    project = _parse_permissions(project_response, "project")
    billing = _parse_permissions(billing_response, "billing")
    project_permissions = _ordered_subset(GCP_PROJECT_PERMISSIONS, project.permissions)
    billing_permissions = _ordered_subset(GCP_BILLING_PERMISSIONS, billing.permissions)
    return GcpIamReceipt(
        project_permissions=project_permissions,
        billing_permissions=billing_permissions,
        project_status=project_response.status_code,
        billing_status=billing_response.status_code,
        evidence=receipt_for(
            "gcp-iam",
            context.project_id,
            context.billing_account_id,
            ",".join(project_permissions),
            ",".join(billing_permissions),
        ),
    )
