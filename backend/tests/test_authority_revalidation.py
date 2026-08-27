from __future__ import annotations

from typing import TYPE_CHECKING

from telco_twin.bootstrap import provider_probes
from telco_twin.bootstrap.preflight_contract import (
    EXPECTED_PERMISSIONS,
    AuthorityReceipt,
    CleanupStatus,
    PreflightReport,
    ProviderResult,
    RepositoryResult,
    receipt_for,
)
from telco_twin.bootstrap.provider_results import (
    ProviderFacts,
    blocked_provider,
    make_provider,
)

if TYPE_CHECKING:
    from pathlib import Path

SHA = "a" * 40


def ready_report() -> PreflightReport:
    providers = tuple(
        make_provider(
            ProviderFacts(
                provider=provider,
                granted_permissions=frozenset(permissions),
                blockers=(),
                cleanup=CleanupStatus.CLEAN,
                seed="forged",
                authority=AuthorityReceipt(
                    identities=(f"forged/{provider}",),
                    request_hashes=(receipt_for("forged-request", provider),),
                    response_hashes=(receipt_for("forged-response", provider),),
                    command_hashes=(receipt_for("forged-command", provider),),
                ),
            )
        )
        for provider, permissions in EXPECTED_PERMISSIONS.items()
    )
    repository = RepositoryResult(
        repository="oyeong011/telco-counterfactual-twin",
        local_worktree_clean=True,
        remote_main_matches_bootstrap=True,
        public_nonfork_main_mit=True,
        workflow_active=True,
        evidence=receipt_for("forged-repository"),
    )
    return PreflightReport(
        schema_version="1.0",
        generated_at="2026-08-27T00:00:00Z",
        bootstrap_sha=SHA,
        outcome="deployment-ready",
        cost_control="preflight-only",
        repository=repository,
        providers=providers,
        temporary_resources=(),
        report_evidence=receipt_for("forged-report"),
    )


def test_fake_read_only_probe_mismatch_rejects_ready_report(tmp_path: Path) -> None:
    # Given
    report = ready_report()
    mismatched = list(report.providers)
    mismatched[3] = blocked_provider("cloudflare", ("account-id-mismatch",))

    def fake_probe(_repo_root: Path, _sha: str) -> tuple[ProviderResult, ...]:
        return tuple(mismatched)

    # When
    matches = provider_probes.revalidate_report_authority(
        report,
        tmp_path,
        fake_probe,
    )

    # Then
    assert matches is False
