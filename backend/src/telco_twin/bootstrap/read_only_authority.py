"""Side-effect-free provider authority probes for report validation."""

from __future__ import annotations

from typing import TYPE_CHECKING

from telco_twin.bootstrap.github_repo_probe import probe_github
from telco_twin.bootstrap.read_only_gcp import probe_gcp_read_only
from telco_twin.bootstrap.read_only_saas import (
    probe_cloudflare_read_only,
    probe_neon_read_only,
)

if TYPE_CHECKING:
    from pathlib import Path

    from telco_twin.bootstrap.preflight_contract import ProviderResult


def probe_read_only_all(
    repo_root: Path,
    bootstrap_sha: str,
) -> tuple[ProviderResult, ...]:
    """Probe every provider without creating or mutating resources."""
    gcp_project, gcp_billing = probe_gcp_read_only()
    return (
        probe_github(repo_root, bootstrap_sha, offline=False),
        gcp_project,
        gcp_billing,
        probe_cloudflare_read_only(),
        probe_neon_read_only(),
    )
