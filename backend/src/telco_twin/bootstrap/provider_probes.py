"""Credential-aware provider-probe orchestration for deployment preflight."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from telco_twin.bootstrap.gcp_authority import probe_gcp_authority
from telco_twin.bootstrap.github_repo_probe import probe_github
from telco_twin.bootstrap.preflight_contract import EXPECTED_PERMISSIONS, ProviderResult
from telco_twin.bootstrap.provider_adapters import DEFAULT_ADAPTERS, ProviderAdapters
from telco_twin.bootstrap.provider_results import blocked_provider
from telco_twin.bootstrap.saas_authority import (
    probe_cloudflare_authority,
    probe_neon_authority,
)

if TYPE_CHECKING:
    from pathlib import Path


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


__all__ = [
    "ProviderAdapters",
    "ProviderProbeRequest",
    "probe_all",
    "probe_github",
    "run_provider_probes",
]
