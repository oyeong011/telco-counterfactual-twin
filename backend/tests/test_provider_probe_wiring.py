from __future__ import annotations

from typing import TYPE_CHECKING

from telco_twin.bootstrap.cloudflare_probe import (
    CloudflareContext,
    CloudflareProbeReceipt,
)
from telco_twin.bootstrap.gcp_commands import GcpContext
from telco_twin.bootstrap.gcp_iam_probe import GcpIamReceipt
from telco_twin.bootstrap.gcp_wif import (
    CleanupReceipt,
    TemporaryProbeReceipt,
    WifApplyReceipt,
)
from telco_twin.bootstrap.neon_probe import NeonContext, NeonProbeReceipt
from telco_twin.bootstrap.preflight_contract import (
    CLOUDFLARE_PERMISSIONS,
    GCP_BILLING_PERMISSIONS,
    GCP_PROJECT_PERMISSIONS,
    GITHUB_PERMISSIONS,
    NEON_PERMISSIONS,
    CleanupStatus,
    ProbeStatus,
    ProviderResult,
)
from telco_twin.bootstrap.provider_probes import (
    ProviderAdapters,
    ProviderProbeRequest,
    run_provider_probes,
)
from telco_twin.bootstrap.provider_results import ProviderFacts, make_provider

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

SHA = "e" * 40
RECEIPT = "sha256:" + ("f" * 64)


def test_probe_all_wires_credential_present_adapters_to_ready_results(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    for name, value in {
        "GCP_PROJECT_ID": "example-project",
        "GCP_REGION": "asia-northeast3",
        "GCP_BILLING_ACCOUNT_ID": "ABC-123",
        "CLOUDFLARE_ACCOUNT_ID": "account-id",
        "CLOUDFLARE_API_TOKEN": "fabricated-cloudflare-token",
        "NEON_API_KEY": "fabricated-neon-key",
        "NEON_ORG_ID": "org-test",
    }.items():
        monkeypatch.setenv(name, value)

    def github_adapter(
        repo_root: Path,
        bootstrap_sha: str,
        *,
        offline: bool,
    ) -> ProviderResult:
        _ = repo_root
        assert bootstrap_sha == SHA
        assert offline is False
        return make_provider(
            ProviderFacts(
                provider="github",
                granted_permissions=frozenset(GITHUB_PERMISSIONS),
                blockers=(),
                cleanup=CleanupStatus.CLEAN,
                seed="github-ready",
            )
        )

    def gcp_context_adapter() -> GcpContext:
        return GcpContext("example-project", "987654321", "ABC-123", "12345678")

    def gcp_iam_adapter(_context: GcpContext) -> GcpIamReceipt:
        return GcpIamReceipt(
            project_permissions=GCP_PROJECT_PERMISSIONS,
            billing_permissions=GCP_BILLING_PERMISSIONS,
            project_status=200,
            billing_status=200,
            evidence=RECEIPT,
        )

    def wif_adapter(context: GcpContext) -> WifApplyReceipt:
        return WifApplyReceipt(
            status="ready",
            project_id=context.project_id,
            project_number=context.project_number,
            pool_id="github-actions",
            provider_id="github-oidc",
            deploy_service_account=(
                "skt-portfolio-deployer@example-project.iam.gserviceaccount.com"
            ),
            cleanup=CleanupReceipt(
                cleanup_complete=True,
                temporary_resources=(),
                restored_bindings=True,
            ),
            temporary_probe=TemporaryProbeReceipt(
                topic_resource="projects/example-project/topics/test",
                budget_resource="billingAccounts/ABC-123/budgets/test",
                budget_schema_version="1.0",
                publisher_policy_evidence=RECEIPT,
                deny_exchange_evidence=RECEIPT,
            ),
            deny_exchange_evidence=RECEIPT,
            evidence=RECEIPT,
        )

    def cloudflare_adapter(_context: CloudflareContext) -> CloudflareProbeReceipt:
        return CloudflareProbeReceipt(
            account_id="account-id",
            project_id="project-id",
            project_name="twin-preflight-test",
            deployment_ids=("deployment-one", "deployment-two"),
            rollback_deployment_id="deployment-one",
            http_statuses=(200, 200, 200, 200, 200, 200, 200, 200, 200),
            cleanup_complete=True,
            evidence=RECEIPT,
        )

    def neon_adapter(_context: NeonContext) -> NeonProbeReceipt:
        return NeonProbeReceipt(
            org_id="org-test",
            project_count=1,
            organization_status=200,
            projects_status=200,
            evidence=RECEIPT,
        )

    adapters = ProviderAdapters(
        github=github_adapter,
        gcp_context=gcp_context_adapter,
        gcp_iam=gcp_iam_adapter,
        wif=wif_adapter,
        cloudflare=cloudflare_adapter,
        neon=neon_adapter,
        which=lambda command: f"/fake/{command}",
    )

    # When
    results = run_provider_probes(
        ProviderProbeRequest(
            repo_root=tmp_path,
            bootstrap_sha=SHA,
            offline=False,
            adapters=adapters,
        )
    )

    # Then
    assert tuple(result.status for result in results) == (
        ProbeStatus.READY,
        ProbeStatus.READY,
        ProbeStatus.READY,
        ProbeStatus.READY,
        ProbeStatus.READY,
    )
    assert tuple(permission.permission for permission in results[1].permissions) == (
        GCP_PROJECT_PERMISSIONS
    )
    assert tuple(permission.permission for permission in results[2].permissions) == (
        GCP_BILLING_PERMISSIONS
    )
    assert tuple(permission.permission for permission in results[3].permissions) == (
        CLOUDFLARE_PERMISSIONS
    )
    assert tuple(permission.permission for permission in results[4].permissions) == NEON_PERMISSIONS


def test_resource_probe_failure_blocks_provider_after_iam_permissions_are_proven() -> None:
    # Given
    facts = ProviderFacts(
        provider="gcp-project",
        granted_permissions=frozenset(GCP_PROJECT_PERMISSIONS),
        blockers=("deny-exchange-unexpected-success",),
        cleanup=CleanupStatus.NOT_CREATED,
        seed="resource-probe-failed",
    )

    # When
    result = make_provider(facts)

    # Then
    assert result.status is ProbeStatus.BLOCKED
    assert all(permission.granted for permission in result.permissions)
    assert result.blockers == ("deny-exchange-unexpected-success",)
