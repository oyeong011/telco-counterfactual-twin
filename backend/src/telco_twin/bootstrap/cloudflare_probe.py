"""Reversible Cloudflare Pages deployment and rollback authority probe."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import ClassVar

import httpx2
from pydantic import BaseModel, ConfigDict, Field

from telco_twin.bootstrap.cloudflare_contract import (
    AccountEnvelope,
    DeploymentsEnvelope,
    OperationEnvelope,
    ProjectEnvelope,
    ProjectsEnvelope,
    TokenEnvelope,
    parse_response,
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
class CreatedProject:
    """Created Pages identity and prerequisite HTTP statuses."""

    project_id: str
    statuses: tuple[int, ...]


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


def _require_equal(actual: str, expected: str, code: str) -> None:
    if actual != expected:
        raise ProviderProbeError(code)


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


def _delete_project(
    context: CloudflareContext,
    transport: httpx2.BaseTransport | None,
    project_name: str,
) -> int:
    headers = {"Authorization": f"Bearer {context.api_token}"}
    with create_http_client(
        "https://api.cloudflare.com/client/v4/",
        headers,
        transport,
    ) as client:
        response = client.delete(f"accounts/{context.account_id}/pages/projects/{project_name}")
        _ = parse_response(response, OperationEnvelope, "pages-delete")
        return response.status_code


def _verify_and_create(
    context: CloudflareContext,
    transport: httpx2.BaseTransport | None,
    project_name: str,
) -> CreatedProject:
    headers = {"Authorization": f"Bearer {context.api_token}"}
    statuses: list[int] = []
    with create_http_client(
        "https://api.cloudflare.com/client/v4/",
        headers,
        transport,
    ) as client:
        token_response = client.get("user/tokens/verify")
        statuses.append(token_response.status_code)
        _ = parse_response(token_response, TokenEnvelope, "token-verify")
        account_response = client.get(f"accounts/{context.account_id}")
        statuses.append(account_response.status_code)
        account = parse_response(account_response, AccountEnvelope, "account-get")
        _require_equal(
            account.result.id,
            context.account_id,
            "cloudflare-account-id-mismatch",
        )
        list_response = client.get(f"accounts/{context.account_id}/pages/projects")
        statuses.append(list_response.status_code)
        _ = parse_response(list_response, ProjectsEnvelope, "pages-list")
        create_response = client.post(
            f"accounts/{context.account_id}/pages/projects",
            json={"name": project_name, "production_branch": "main"},
        )
        statuses.append(create_response.status_code)
        try:
            project = parse_response(create_response, ProjectEnvelope, "pages-create")
            _require_equal(
                project.result.name,
                project_name,
                "cloudflare-project-name-mismatch",
            )
        except ProviderProbeError:
            if create_response.status_code == HTTP_OK:
                _ = _delete_project(context, transport, project_name)
            raise
        return CreatedProject(project_id=project.result.id, statuses=tuple(statuses))


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
    created: CreatedProject | None = None
    proof: DeploymentProof | None = None
    primary_error: ProviderProbeError | None = None
    cleanup_status: int | None = None
    try:
        created = _verify_and_create(context, active_transports.api, project_name)
        proof = _deploy_and_rollback(context, active_transports, project_name)
    except ProviderProbeError as error:
        primary_error = error
    except httpx2.HTTPError:
        code = "cloudflare-network-failed"
        primary_error = ProviderProbeError(code)
    finally:
        if created is not None:
            try:
                cleanup_status = _delete_project(
                    context,
                    active_transports.api,
                    project_name,
                )
            except (ProviderProbeError, httpx2.HTTPError):
                cleanup_status = None
    if created is not None and cleanup_status is None:
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
