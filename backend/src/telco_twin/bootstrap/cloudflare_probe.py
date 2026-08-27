"""Reversible Cloudflare Pages deployment and rollback authority probe."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import ClassVar, assert_never

import httpx2
from pydantic import BaseModel, ConfigDict, Field

from telco_twin.bootstrap.cloudflare_contract import (
    DeploymentsEnvelope,
    OperationEnvelope,
    parse_response,
)
from telco_twin.bootstrap.cloudflare_project import (
    CreatedProject,
    ProjectCreationRejected,
    ProjectProbeRequest,
    delete_project,
    verify_and_create,
)
from telco_twin.bootstrap.gcp_commands import run_command
from telco_twin.bootstrap.http_client import create_http_client
from telco_twin.bootstrap.preflight_contract import receipt_for
from telco_twin.bootstrap.probe_errors import ProviderProbeError

HTTP_OK = 200


@dataclass(frozen=True, slots=True)
class CloudflareContext:
    """Cloudflare authority and source identifiers."""

    account_id: str
    api_token: str
    source_sha: str
    wrangler_command: str


@dataclass(frozen=True, slots=True)
class CloudflareTransports:
    """Injectable API and public-content wire transports."""

    api: httpx2.BaseTransport | None = None
    public: httpx2.BaseTransport | None = None


@dataclass(frozen=True, slots=True)
class DeploymentProof:
    """Two deployment IDs, rollback target, and HTTP statuses."""

    first: str
    second: str
    statuses: tuple[int, ...]


class CloudflareProbeReceipt(BaseModel):
    """Non-secret Pages rollback and cleanup receipt."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    account_id: str
    project_id: str
    project_name: str
    deployment_ids: tuple[str, str]
    rollback_deployment_id: str
    http_statuses: tuple[int, ...]
    cleanup_complete: bool
    evidence: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


def _require_rollback_content(response: httpx2.Response) -> None:
    if response.status_code != HTTP_OK or response.text != "version-one":
        code = "cloudflare-rollback-content-mismatch"
        raise ProviderProbeError(code)


def _deploy(context: CloudflareContext, directory: Path, project_name: str) -> None:
    deployed = run_command(
        (
            context.wrangler_command,
            "pages",
            "deploy",
            str(directory),
            f"--project-name={project_name}",
            "--branch=main",
            f"--commit-hash={context.source_sha}",
            "--commit-message=preflight-authority-probe",
        )
    )
    if deployed.returncode != 0:
        code = "cloudflare-deploy-failed"
        raise ProviderProbeError(code)


def _deployment_id(response: httpx2.Response, excluded: frozenset[str]) -> str:
    deployments = parse_response(
        response,
        DeploymentsEnvelope,
        "pages-deployments-list",
    )
    available = tuple(item.id for item in deployments.result if item.id not in excluded)
    if len(available) != 1:
        code = "cloudflare-deployment-id-unresolved"
        raise ProviderProbeError(code)
    return available[0]


def _deploy_and_rollback(
    context: CloudflareContext,
    transports: CloudflareTransports,
    project_name: str,
) -> DeploymentProof:
    headers = {"Authorization": f"Bearer {context.api_token}"}
    statuses: list[int] = []
    project_path = f"accounts/{context.account_id}/pages/projects/{project_name}"
    with create_http_client(
        "https://api.cloudflare.com/client/v4/",
        headers,
        transports.api,
    ) as client:
        with TemporaryDirectory(prefix="twin-pages-probe-") as temp_dir:
            root = Path(temp_dir)
            first = root / "first"
            second = root / "second"
            first.mkdir()
            second.mkdir()
            _ = (first / "index.html").write_text("version-one", encoding="utf-8")
            _ = (second / "index.html").write_text("version-two", encoding="utf-8")
            _deploy(context, first, project_name)
            first_list = client.get(f"{project_path}/deployments")
            statuses.append(first_list.status_code)
            first_id = _deployment_id(first_list, frozenset())
            _deploy(context, second, project_name)
            second_list = client.get(f"{project_path}/deployments")
            statuses.append(second_list.status_code)
            second_id = _deployment_id(second_list, frozenset((first_id,)))
        rollback = client.post(f"{project_path}/deployments/{first_id}/rollback")
        statuses.append(rollback.status_code)
        _ = parse_response(rollback, OperationEnvelope, "pages-rollback")
    with create_http_client(
        "https://example.invalid",
        {},
        transports.public,
    ) as public_client:
        content = public_client.get(f"https://{project_name}.pages.dev")
        statuses.append(content.status_code)
        _require_rollback_content(content)
    return DeploymentProof(first=first_id, second=second_id, statuses=tuple(statuses))


def probe_cloudflare(
    context: CloudflareContext,
    transports: CloudflareTransports | None = None,
    *,
    suffix: str | None = None,
) -> CloudflareProbeReceipt:
    """Prove token/account/Pages/deploy/rollback/content authority and trap cleanup."""
    active_transports = transports or CloudflareTransports()
    project_name = f"twin-preflight-{suffix or secrets.token_hex(6)}"
    project_request = ProjectProbeRequest(
        account_id=context.account_id,
        api_token=context.api_token,
        project_name=project_name,
        transport=active_transports.api,
    )
    creation: CreatedProject | ProjectCreationRejected | None = None
    created: CreatedProject | None = None
    proof: DeploymentProof | None = None
    primary_error: ProviderProbeError | None = None
    cleanup_status: int | None = None
    try:
        creation = verify_and_create(project_request)
        match creation:
            case CreatedProject() as project:
                created = project
                proof = _deploy_and_rollback(context, active_transports, project_name)
            case ProjectCreationRejected(error=error):
                primary_error = error
            case _:
                assert_never(creation)
    except ProviderProbeError as error:
        primary_error = error
    except httpx2.HTTPError:
        code = "cloudflare-network-failed"
        primary_error = ProviderProbeError(code)
    finally:
        if creation is not None:
            try:
                cleanup_status = delete_project(project_request)
            except (ProviderProbeError, httpx2.HTTPError):
                cleanup_status = None
    if creation is not None and cleanup_status is None:
        code = "cloudflare-cleanup-failed"
        raise ProviderProbeError(code)
    if primary_error is not None:
        raise primary_error
    if created is None or proof is None or cleanup_status is None:
        code = "cloudflare-probe-incomplete"
        raise ProviderProbeError(code)
    statuses = created.statuses + proof.statuses + (cleanup_status,)
    return CloudflareProbeReceipt(
        account_id=context.account_id,
        project_id=created.project_id,
        project_name=project_name,
        deployment_ids=(proof.first, proof.second),
        rollback_deployment_id=proof.first,
        http_statuses=statuses,
        cleanup_complete=True,
        evidence=receipt_for(
            "cloudflare-pages",
            context.account_id,
            created.project_id,
            proof.first,
            proof.second,
            ",".join(str(status) for status in statuses),
        ),
    )
