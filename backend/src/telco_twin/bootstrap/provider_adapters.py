"""Typed dependency adapters and prerequisite checks for provider probes."""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Protocol

from telco_twin.bootstrap.cloudflare_probe import (
    CloudflareContext,
    CloudflareProbeReceipt,
    probe_cloudflare,
)
from telco_twin.bootstrap.gcp_commands import GcpContext, run_command
from telco_twin.bootstrap.gcp_iam_probe import GcpIamReceipt, probe_gcp_iam
from telco_twin.bootstrap.gcp_wif import WifApplyReceipt, apply_wif
from telco_twin.bootstrap.github_repo_probe import probe_github
from telco_twin.bootstrap.neon_probe import NeonContext, NeonProbeReceipt, probe_neon
from telco_twin.bootstrap.probe_errors import ProviderProbeError

if TYPE_CHECKING:
    from pathlib import Path

    from telco_twin.bootstrap.preflight_contract import ProviderResult

type GcpContextAdapter = Callable[[], GcpContext]
type GcpIamAdapter = Callable[[GcpContext], GcpIamReceipt]
type WifAdapter = Callable[[GcpContext], WifApplyReceipt]
type CloudflareAdapter = Callable[[CloudflareContext], CloudflareProbeReceipt]
type NeonAdapter = Callable[[NeonContext], NeonProbeReceipt]
type CommandFinder = Callable[[str], str | None]


class GitHubAdapter(Protocol):
    """Exact-head GitHub provider adapter."""

    def __call__(
        self,
        repo_root: Path,
        bootstrap_sha: str,
        *,
        offline: bool,
    ) -> ProviderResult:
        """Probe the repository and exact workflow head."""
        ...


def resolve_gcp_context() -> GcpContext:
    """Resolve non-secret project/owner identifiers after prerequisites are present."""
    project_id = os.environ["GCP_PROJECT_ID"]
    project = run_command(
        (
            "gcloud",
            "projects",
            "describe",
            project_id,
            "--format=value(projectNumber)",
        )
    )
    owner = run_command(("gh", "api", "users/oyeong011", "--jq", ".id"))
    project_number = project.stdout.strip()
    owner_id = owner.stdout.strip()
    if (
        project.returncode != 0
        or owner.returncode != 0
        or not project_number.isdigit()
        or not owner_id.isdigit()
    ):
        code = "gcp-context-resolution-failed"
        raise ProviderProbeError(code)
    return GcpContext(
        project_id=project_id,
        project_number=project_number,
        billing_account_id=os.environ["GCP_BILLING_ACCOUNT_ID"],
        owner_id=owner_id,
    )


def _gcp_iam(context: GcpContext) -> GcpIamReceipt:
    return probe_gcp_iam(context)


def _cloudflare(context: CloudflareContext) -> CloudflareProbeReceipt:
    return probe_cloudflare(context)


def _neon(context: NeonContext) -> NeonProbeReceipt:
    return probe_neon(context)


@dataclass(frozen=True, slots=True)
class ProviderAdapters:
    """Injectable provider boundaries used by production and fake-wire tests."""

    github: GitHubAdapter
    gcp_context: GcpContextAdapter
    gcp_iam: GcpIamAdapter
    wif: WifAdapter
    cloudflare: CloudflareAdapter
    neon: NeonAdapter
    which: CommandFinder


DEFAULT_ADAPTERS: Final = ProviderAdapters(
    github=probe_github,
    gcp_context=resolve_gcp_context,
    gcp_iam=_gcp_iam,
    wif=apply_wif,
    cloudflare=_cloudflare,
    neon=_neon,
    which=shutil.which,
)


def missing_prerequisites(
    adapters: ProviderAdapters,
    command: str | None,
    environment_names: tuple[str, ...],
) -> tuple[str, ...]:
    """Return only missing command/environment names, never their values."""
    blockers: list[str] = []
    if command is not None and adapters.which(command) is None:
        blockers.append(f"missing-command:{command}")
    blockers.extend(f"missing-env:{name}" for name in environment_names if not os.environ.get(name))
    return tuple(blockers)
