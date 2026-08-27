"""Cloudflare Pages project creation and cleanup transaction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from telco_twin.bootstrap.cloudflare_contract import (
    AccountEnvelope,
    OperationEnvelope,
    ProjectEnvelope,
    ProjectsEnvelope,
    TokenEnvelope,
    parse_response,
)
from telco_twin.bootstrap.http_client import create_http_client
from telco_twin.bootstrap.probe_errors import ProviderProbeError

if TYPE_CHECKING:
    import httpx2

HTTP_SUCCESS_MIN = 200
HTTP_SUCCESS_MAX = 300


@dataclass(frozen=True, slots=True)
class ProjectProbeRequest:
    """Account-bound unique project request and injectable transport."""

    account_id: str
    api_token: str
    project_name: str
    transport: httpx2.BaseTransport | None


@dataclass(frozen=True, slots=True)
class CreatedProject:
    """Strictly parsed Pages identity and prerequisite HTTP statuses."""

    project_id: str
    statuses: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class ProjectCreationRejected:
    """Successful create whose strict response contract was rejected."""

    error: ProviderProbeError


type ProjectCreation = CreatedProject | ProjectCreationRejected


def _headers(request: ProjectProbeRequest) -> dict[str, str]:
    return {"Authorization": f"Bearer {request.api_token}"}


def delete_project(request: ProjectProbeRequest) -> int:
    """Delete only the unique requested project under its resolved account."""
    with create_http_client(
        "https://api.cloudflare.com/client/v4/",
        _headers(request),
        request.transport,
    ) as client:
        response = client.delete(
            f"accounts/{request.account_id}/pages/projects/{request.project_name}"
        )
        _ = parse_response(response, OperationEnvelope, "pages-delete")
        return response.status_code


def verify_and_create(request: ProjectProbeRequest) -> ProjectCreation:
    """Verify prerequisites and register cleanup after every successful create."""
    statuses: list[int] = []
    with create_http_client(
        "https://api.cloudflare.com/client/v4/",
        _headers(request),
        request.transport,
    ) as client:
        token_response = client.get("user/tokens/verify")
        statuses.append(token_response.status_code)
        _ = parse_response(token_response, TokenEnvelope, "token-verify")
        account_response = client.get(f"accounts/{request.account_id}")
        statuses.append(account_response.status_code)
        account = parse_response(account_response, AccountEnvelope, "account-get")
        if account.result.id != request.account_id:
            code = "cloudflare-account-id-mismatch"
            raise ProviderProbeError(code)
        list_response = client.get(f"accounts/{request.account_id}/pages/projects")
        statuses.append(list_response.status_code)
        _ = parse_response(list_response, ProjectsEnvelope, "pages-list")
        create_response = client.post(
            f"accounts/{request.account_id}/pages/projects",
            json={"name": request.project_name, "production_branch": "main"},
        )
        statuses.append(create_response.status_code)
        try:
            project = parse_response(create_response, ProjectEnvelope, "pages-create")
        except ProviderProbeError as error:
            if HTTP_SUCCESS_MIN <= create_response.status_code < HTTP_SUCCESS_MAX:
                return ProjectCreationRejected(error=error)
            raise
        if project.result.name != request.project_name:
            return ProjectCreationRejected(
                error=ProviderProbeError("cloudflare-project-name-mismatch"),
            )
        return CreatedProject(
            project_id=project.result.id,
            statuses=tuple(statuses),
        )
