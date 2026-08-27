"""Credential-aware provider-probe orchestration for deployment preflight."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from telco_twin.bootstrap.gcp_authority import probe_gcp_authority
from telco_twin.bootstrap.github_repo_probe import probe_github
from telco_twin.bootstrap.preflight_contract import (
    EXPECTED_PERMISSIONS,
    PreflightReport,
    ProbeStatus,
    ProviderResult,
)
from telco_twin.bootstrap.provider_adapters import DEFAULT_ADAPTERS, ProviderAdapters
from telco_twin.bootstrap.provider_results import blocked_provider
from telco_twin.bootstrap.read_only_authority import probe_read_only_all
from telco_twin.bootstrap.saas_authority import (
    probe_cloudflare_authority,
    probe_neon_authority,
)

if TYPE_CHECKING:
    from pathlib import Path

type ReadOnlyProbe = Callable[[Path, str], tuple[ProviderResult, ...]]


@dataclass(frozen=True, slots=True)
class ProviderProbeRequest:
    """Repository identity and provider adapters for one preflight run."""

    repo_root: Path
    bootstrap_sha: str
    offline: bool
    adapters: ProviderAdapters = DEFAULT_ADAPTERS


def run_provider_probes(request: ProviderProbeRequest) -> tuple[ProviderResult, ...]:
    """Run every provider through typed adapters in canonical report order."""
    if request.offline:
        return tuple(
            blocked_provider(provider, ("offline-mode",)) for provider in EXPECTED_PERMISSIONS
        )
    gcp_project, gcp_billing = probe_gcp_authority(request.adapters)
    return (
        request.adapters.github(
            request.repo_root,
            request.bootstrap_sha,
            offline=False,
        ),
        gcp_project,
        gcp_billing,
        probe_cloudflare_authority(request.adapters, request.bootstrap_sha),
        probe_neon_authority(request.adapters),
    )


def probe_all(repo_root: Path, bootstrap_sha: str, offline: bool) -> tuple[ProviderResult, ...]:
    """Compatibility wrapper used by the deployment-preflight CLI."""
    return run_provider_probes(
        ProviderProbeRequest(
            repo_root=repo_root,
            bootstrap_sha=bootstrap_sha,
            offline=offline,
        )
    )


def revalidate_report_authority(
    report: PreflightReport,
    repo_root: Path,
    probe: ReadOnlyProbe = probe_read_only_all,
) -> bool:
    """Compare untrusted claims with fresh side-effect-free provider facts."""
    observed = probe(repo_root, report.bootstrap_sha)
    if len(observed) != len(report.providers):
        return False
    for claimed, current in zip(report.providers, observed, strict=True):
        claimed_permissions = tuple(
            (item.permission, item.granted, item.status) for item in claimed.permissions
        )
        current_permissions = tuple(
            (item.permission, item.granted, item.status) for item in current.permissions
        )
        if (
            claimed.provider != current.provider
            or claimed.status is not current.status
            or claimed.blockers != current.blockers
            or claimed_permissions != current_permissions
        ):
            return False
        if claimed.status is ProbeStatus.READY:
            authority = claimed.authority
            if (
                not authority.identities
                or not authority.request_hashes
                or not authority.response_hashes
                or authority != current.authority
            ):
                return False
    github_ready = observed[0].status is ProbeStatus.READY
    return (
        report.repository.remote_main_matches_bootstrap is github_ready
        and report.repository.public_nonfork_main_mit is github_ready
        and report.repository.workflow_active is github_ready
    )


__all__ = [
    "ProviderAdapters",
    "ProviderProbeRequest",
    "probe_all",
    "probe_github",
    "revalidate_report_authority",
    "run_provider_probes",
]
