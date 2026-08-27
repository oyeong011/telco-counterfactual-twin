"""GET-only Neon organization and projects authority probe."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

import httpx2
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from telco_twin.bootstrap.http_client import create_http_client
from telco_twin.bootstrap.preflight_contract import receipt_for
from telco_twin.bootstrap.probe_errors import ProviderProbeError

HTTP_OK = 200


@dataclass(frozen=True, slots=True)
class NeonContext:
    """Neon organization identifier and API credential."""

    org_id: str
    api_key: str


class OrganizationResponse(BaseModel):
    """Neon Organization response projection from the official v2 schema."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)
    id: str = Field(pattern=r"^[a-z0-9-]{1,60}$")


class ProjectResponse(BaseModel):
    """Neon project list item projection."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)
    id: str = Field(pattern=r"^[a-z0-9-]{1,60}$")


class ProjectsResponse(BaseModel):
    """Neon ProjectsResponse projection from the official v2 schema."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)
    projects: tuple[ProjectResponse, ...]


class NeonProbeReceipt(BaseModel):
    """Non-secret GET authority receipt."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    org_id: str
    project_count: int = Field(ge=0)
    organization_status: int = Field(ge=100, le=599)
    projects_status: int = Field(ge=100, le=599)
    evidence: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


def _parse[T: BaseModel](response: httpx2.Response, model: type[T], operation: str) -> T:
    if response.status_code != HTTP_OK:
        code = f"neon-{operation}-http-{response.status_code}"
        raise ProviderProbeError(code)
    try:
        return model.model_validate_json(response.content)
    except ValidationError:
        code = f"neon-{operation}-invalid-json"
        raise ProviderProbeError(code) from None


def probe_neon(
    context: NeonContext,
    transport: httpx2.BaseTransport | None = None,
) -> NeonProbeReceipt:
    """Prove organization and project-list GET authority without lifecycle mutation."""
    headers = {"Authorization": f"Bearer {context.api_key}"}
    try:
        with create_http_client(
            "https://console.neon.tech/api/v2/",
            headers,
            transport,
        ) as client:
            organization_response = client.get(f"organizations/{context.org_id}")
            projects_response = client.get(
                "projects",
                params={"org_id": context.org_id, "limit": 1},
            )
    except httpx2.HTTPError:
        code = "neon-network-failed"
        raise ProviderProbeError(code) from None
    organization = _parse(organization_response, OrganizationResponse, "organization")
    projects = _parse(projects_response, ProjectsResponse, "projects")
    if organization.id != context.org_id:
        code = "neon-organization-id-mismatch"
        raise ProviderProbeError(code)
    return NeonProbeReceipt(
        org_id=organization.id,
        project_count=len(projects.projects),
        organization_status=organization_response.status_code,
        projects_status=projects_response.status_code,
        evidence=receipt_for(
            "neon-get",
            organization.id,
            str(len(projects.projects)),
            str(organization_response.status_code),
            str(projects_response.status_code),
        ),
    )
