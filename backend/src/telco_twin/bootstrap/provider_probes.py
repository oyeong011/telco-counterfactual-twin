"""Read-only provider probes for the deployment preflight."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from typing import TYPE_CHECKING, ClassVar, Final

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from telco_twin.bootstrap.preflight_contract import (
    EXPECTED_PERMISSIONS,
    CleanupStatus,
    PermissionResult,
    ProbeStatus,
    ProviderName,
    ProviderResult,
    receipt_for,
)

if TYPE_CHECKING:
    from pathlib import Path

REPOSITORY: Final = "oyeong011/telco-counterfactual-twin"


class GitHubLicense(BaseModel):
    """GitHub license projection."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)
    spdx_id: str


class GitHubRepository(BaseModel):
    """GitHub repository fields used by the gate."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)
    id: int
    private: bool
    fork: bool
    default_branch: str
    license: GitHubLicense | None


class GitHubWorkflow(BaseModel):
    """GitHub workflow state projection."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)
    id: int
    state: str


class GitHubPermission(BaseModel):
    """Authenticated collaborator permission projection."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)
    permission: str


class GitHubRun(BaseModel):
    """Workflow run head projection."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)
    head_sha: str = Field(pattern=r"^[0-9a-f]{40}$")


class GitHubRuns(BaseModel):
    """GitHub workflow runs envelope."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)
    workflow_runs: tuple[GitHubRun, ...]


def _run(arguments: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 -- argv is constructed internally and never uses a shell.
        arguments, cwd=cwd, check=False, capture_output=True, text=True
    )


def _permission_result(
    provider: ProviderName, permission: str, granted: bool, seed: str
) -> PermissionResult:
    status = ProbeStatus.READY if granted else ProbeStatus.BLOCKED
    return PermissionResult(
        permission=permission,
        granted=granted,
        status=status,
        evidence=receipt_for(provider, permission, str(granted), seed),
    )


def make_provider(
    provider: ProviderName,
    granted_permissions: frozenset[str],
    blockers: tuple[str, ...],
    cleanup: CleanupStatus,
    seed: str,
) -> ProviderResult:
    """Build a complete provider result from explicit permission facts."""
    permissions = tuple(
        _permission_result(provider, permission, permission in granted_permissions, seed)
        for permission in EXPECTED_PERMISSIONS[provider]
    )
    status = (
        ProbeStatus.READY if len(granted_permissions) == len(permissions) else ProbeStatus.BLOCKED
    )
    return ProviderResult(
        provider=provider,
        status=status,
        permissions=permissions,
        blockers=blockers,
        cleanup=cleanup,
        evidence=receipt_for(provider, status, seed),
    )


def blocked_provider(provider: ProviderName, blockers: tuple[str, ...]) -> ProviderResult:
    """Represent unavailable authority without claiming a permission probe ran."""
    return make_provider(provider, frozenset(), blockers, CleanupStatus.NOT_CREATED, "blocked")


def probe_github(repo_root: Path, bootstrap_sha: str, offline: bool) -> ProviderResult:
    """Verify public metadata, workflow visibility, dispatch evidence, and admin equivalence."""
    if offline:
        return blocked_provider("github", ("offline-mode",))
    if shutil.which("gh") is None:
        return blocked_provider("github", ("missing-command:gh",))

    remote = _run(["git", "ls-remote", "origin", "refs/heads/main"], repo_root)
    repo = _run(["gh", "api", f"repos/{REPOSITORY}"], repo_root)
    workflow = _run(["gh", "api", f"repos/{REPOSITORY}/actions/workflows/wif-probe.yml"], repo_root)
    permission = _run(
        ["gh", "api", f"repos/{REPOSITORY}/collaborators/oyeong011/permission"],
        repo_root,
    )
    runs = _run(
        [
            "gh",
            "api",
            "--method",
            "GET",
            f"repos/{REPOSITORY}/actions/workflows/wif-probe.yml/runs",
            "-f",
            "event=workflow_dispatch",
            "-f",
            "per_page=20",
        ],
        repo_root,
    )
    outputs = (
        remote.stdout,
        repo.stdout,
        workflow.stdout,
        permission.stdout,
        runs.stdout,
    )
    seed = hashlib.sha256("\0".join(outputs).encode()).hexdigest()
    try:
        repo_data = (
            GitHubRepository.model_validate_json(repo.stdout) if repo.returncode == 0 else None
        )
        workflow_data = (
            GitHubWorkflow.model_validate_json(workflow.stdout)
            if workflow.returncode == 0
            else None
        )
        permission_data = (
            GitHubPermission.model_validate_json(permission.stdout)
            if permission.returncode == 0
            else None
        )
        runs_data = GitHubRuns.model_validate_json(runs.stdout) if runs.returncode == 0 else None
    except ValidationError:
        return blocked_provider("github", ("invalid-github-api-response",))

    remote_matches = (
        remote.returncode == 0 and remote.stdout.split("\t", 1)[0].strip() == bootstrap_sha
    )
    public_metadata = (
        repo_data is not None
        and not repo_data.private
        and not repo_data.fork
        and repo_data.default_branch == "main"
        and repo_data.license is not None
        and repo_data.license.spdx_id == "MIT"
    )
    workflow_active = workflow_data is not None and workflow_data.state == "active"
    dispatched_head = runs_data is not None and any(
        item.head_sha == bootstrap_sha for item in runs_data.workflow_runs
    )
    admin = permission_data is not None and permission_data.permission == "admin"
    facts = {
        "repo.public": public_metadata and remote_matches,
        "workflow.read": workflow_active,
        "workflow.dispatch": dispatched_head,
        "repo.admin": admin,
    }
    granted = frozenset(name for name, value in facts.items() if value)
    blockers = tuple(f"unproven:{name}" for name, value in facts.items() if not value)
    cleanup = CleanupStatus.CLEAN if not blockers else CleanupStatus.NOT_CREATED
    return make_provider("github", granted, blockers, cleanup, seed)


def missing_authority(
    provider: ProviderName,
    command: str,
    environment_names: tuple[str, ...],
) -> ProviderResult:
    """Report missing local command/config prerequisites without reading values into output."""
    blockers: list[str] = []
    if shutil.which(command) is None:
        blockers.append(f"missing-command:{command}")
    blockers.extend(f"missing-env:{name}" for name in environment_names if not os.environ.get(name))
    if blockers:
        return blocked_provider(provider, tuple(blockers))
    return blocked_provider(provider, ("reversible-authority-probe-not-run",))


def probe_all(repo_root: Path, bootstrap_sha: str, offline: bool) -> tuple[ProviderResult, ...]:
    """Run the safe provider probes; unavailable authorities remain explicitly blocked."""
    if offline:
        return tuple(
            blocked_provider(provider, ("offline-mode",)) for provider in EXPECTED_PERMISSIONS
        )
    return (
        probe_github(repo_root, bootstrap_sha, offline=False),
        missing_authority("gcp-project", "gcloud", ("GCP_PROJECT_ID", "GCP_REGION")),
        missing_authority("gcp-billing", "gcloud", ("GCP_BILLING_ACCOUNT_ID",)),
        missing_authority(
            "cloudflare",
            "wrangler",
            ("CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN"),
        ),
        missing_authority("neon", "neonctl", ("NEON_API_KEY", "NEON_ORG_ID")),
    )
