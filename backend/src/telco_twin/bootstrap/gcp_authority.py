"""GCP IAM, WIF, budget, topic, publisher, and cleanup authority composition."""

from __future__ import annotations

from typing import TYPE_CHECKING

from telco_twin.bootstrap.gcp_commands import GcpContext, ProvisioningError
from telco_twin.bootstrap.preflight_contract import (
    GCP_BILLING_PERMISSIONS,
    GCP_PROJECT_PERMISSIONS,
    AuthorityReceipt,
    CleanupStatus,
    ProviderResult,
    receipt_for,
)
from telco_twin.bootstrap.probe_errors import ProviderProbeError
from telco_twin.bootstrap.provider_adapters import (
    ProviderAdapters,
    missing_prerequisites,
)
from telco_twin.bootstrap.provider_results import (
    ProviderFacts,
    blocked_provider,
    make_provider,
)

if TYPE_CHECKING:
    from telco_twin.bootstrap.gcp_iam_probe import GcpIamReceipt


def gcp_project_authority(
    context: GcpContext,
    iam: GcpIamReceipt,
) -> AuthorityReceipt:
    """Build stable project/resource/read-request identity evidence."""
    service_account = f"skt-portfolio-deployer@{context.project_id}.iam.gserviceaccount.com"
    return AuthorityReceipt(
        identities=(
            f"projects/{context.project_id}",
            f"projects/{context.project_number}",
            service_account,
            (
                f"projects/{context.project_number}/locations/global/"
                "workloadIdentityPools/github-actions/providers/github-oidc"
            ),
        ),
        request_hashes=(receipt_for("gcp-project-test-permissions", *GCP_PROJECT_PERMISSIONS),),
        response_hashes=(iam.evidence,),
        command_hashes=(
            receipt_for("gcloud", "projects", "describe", context.project_id),
            receipt_for("gcloud", "auth", "print-access-token"),
        ),
    )


def gcp_billing_authority(
    context: GcpContext,
    iam: GcpIamReceipt,
) -> AuthorityReceipt:
    """Build stable billing-account/read-request identity evidence."""
    return AuthorityReceipt(
        identities=(f"billingAccounts/{context.billing_account_id}",),
        request_hashes=(receipt_for("gcp-billing-test-permissions", *GCP_BILLING_PERMISSIONS),),
        response_hashes=(iam.evidence,),
        command_hashes=(receipt_for("gcloud", "auth", "print-access-token"),),
    )


def probe_gcp_authority(adapters: ProviderAdapters) -> tuple[ProviderResult, ProviderResult]:
    """Probe exact IAM subsets, then persistent WIF and reversible GCP resources."""
    project_prerequisites = missing_prerequisites(
        adapters,
        "gcloud",
        ("GCP_PROJECT_ID", "GCP_REGION"),
    )
    billing_prerequisites = missing_prerequisites(
        adapters,
        "gcloud",
        ("GCP_BILLING_ACCOUNT_ID",),
    )
    github_prerequisites = missing_prerequisites(adapters, "gh", ())
    if project_prerequisites or billing_prerequisites or github_prerequisites:
        return (
            blocked_provider(
                "gcp-project",
                project_prerequisites + github_prerequisites,
            ),
            blocked_provider(
                "gcp-billing",
                billing_prerequisites + github_prerequisites,
            ),
        )
    try:
        context = adapters.gcp_context()
        iam = adapters.gcp_iam(context)
    except ProviderProbeError as error:
        blockers = (error.code,)
        return (
            blocked_provider("gcp-project", blockers),
            blocked_provider("gcp-billing", blockers),
        )
    project_granted = frozenset(iam.project_permissions)
    billing_granted = frozenset(iam.billing_permissions)
    project_blockers = tuple(
        f"unproven:{permission}"
        for permission in GCP_PROJECT_PERMISSIONS
        if permission not in project_granted
    )
    billing_blockers = tuple(
        f"unproven:{permission}"
        for permission in GCP_BILLING_PERMISSIONS
        if permission not in billing_granted
    )
    cleanup = CleanupStatus.NOT_CREATED
    wif_evidence = "not-run"
    if not project_blockers and not billing_blockers:
        try:
            wif = adapters.wif(context)
        except ProvisioningError as error:
            project_blockers = (error.code,)
            billing_blockers = (error.code,)
        else:
            cleanup = CleanupStatus.RESTORED
            wif_evidence = wif.evidence
    seed = f"{iam.evidence}:{wif_evidence}"
    project_authority = gcp_project_authority(context, iam)
    billing_authority = gcp_billing_authority(context, iam)
    return (
        make_provider(
            ProviderFacts(
                provider="gcp-project",
                granted_permissions=project_granted,
                blockers=project_blockers,
                cleanup=cleanup,
                seed=seed,
                authority=project_authority,
            )
        ),
        make_provider(
            ProviderFacts(
                provider="gcp-billing",
                granted_permissions=billing_granted,
                blockers=billing_blockers,
                cleanup=cleanup,
                seed=seed,
                authority=billing_authority,
            )
        ),
    )
