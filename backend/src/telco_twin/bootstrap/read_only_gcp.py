"""Side-effect-free GCP authority revalidation."""

from __future__ import annotations

from typing import TYPE_CHECKING

from telco_twin.bootstrap.gcp_authority import (
    gcp_billing_authority,
    gcp_project_authority,
)
from telco_twin.bootstrap.gcp_commands import run_command
from telco_twin.bootstrap.gcp_persistent_contract import (
    ISSUER,
    MAPPING,
    ProviderSnapshot,
)
from telco_twin.bootstrap.preflight_contract import (
    GCP_BILLING_PERMISSIONS,
    GCP_PROJECT_PERMISSIONS,
    CleanupStatus,
    ProviderResult,
)
from telco_twin.bootstrap.probe_errors import ProviderProbeError
from telco_twin.bootstrap.provider_adapters import (
    DEFAULT_ADAPTERS,
    ProviderAdapters,
    missing_prerequisites,
)
from telco_twin.bootstrap.provider_results import (
    ProviderFacts,
    blocked_provider,
    make_provider,
)

if TYPE_CHECKING:
    from telco_twin.bootstrap.gcp_commands import GcpContext


def _unproven(
    permissions: tuple[str, ...],
    granted: frozenset[str],
) -> tuple[str, ...]:
    return tuple(
        f"unproven:{permission}" for permission in permissions if permission not in granted
    )


def _gcp_resources_ready(context: GcpContext) -> tuple[bool, bool]:
    service_account = f"skt-portfolio-deployer@{context.project_id}.iam.gserviceaccount.com"
    project_commands = (
        (
            "gcloud",
            "iam",
            "service-accounts",
            "describe",
            service_account,
        ),
        (
            "gcloud",
            "iam",
            "workload-identity-pools",
            "describe",
            "github-actions",
            f"--project={context.project_id}",
            "--location=global",
        ),
        (
            "gcloud",
            "iam",
            "workload-identity-pools",
            "providers",
            "describe",
            "github-oidc",
            f"--project={context.project_id}",
            "--location=global",
            "--workload-identity-pool=github-actions",
            "--format=json",
        ),
    )
    results = tuple(run_command(command) for command in project_commands)
    project_ready = all(result.returncode == 0 for result in results)
    if project_ready:
        try:
            snapshot = ProviderSnapshot.model_validate_json(results[-1].stdout)
        except ValueError:
            project_ready = False
        else:
            expected_mapping: dict[str, str] = {}
            for item in MAPPING.split(","):
                key, value = item.split("=", 1)
                expected_mapping[key] = value
            expected_condition = (
                f"assertion.repository_owner_id=='{context.owner_id}' && "
                "assertion.repository in "
                "['oyeong011/telco-counterfactual-twin',"
                "'oyeong011/mcp-evidence-plane']"
            )
            project_ready = (
                snapshot.issuer == ISSUER
                and snapshot.mapping == expected_mapping
                and snapshot.condition == expected_condition
            )
    billing = run_command(
        (
            "gcloud",
            "billing",
            "accounts",
            "describe",
            context.billing_account_id,
            "--format=value(name)",
        )
    )
    billing_ready = (
        billing.returncode == 0
        and billing.stdout.strip() == f"billingAccounts/{context.billing_account_id}"
    )
    return project_ready, billing_ready


def probe_gcp_read_only(
    adapters: ProviderAdapters = DEFAULT_ADAPTERS,
) -> tuple[ProviderResult, ProviderResult]:
    """Revalidate GCP IAM plus persistent resource/account identities."""
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
    project_blockers = _unproven(GCP_PROJECT_PERMISSIONS, project_granted)
    billing_blockers = _unproven(GCP_BILLING_PERMISSIONS, billing_granted)
    project_resource_ready, billing_resource_ready = _gcp_resources_ready(context)
    if not project_resource_ready:
        project_blockers += ("persistent-resource-mismatch",)
    if not billing_resource_ready:
        billing_blockers += ("billing-account-mismatch",)
    return (
        make_provider(
            ProviderFacts(
                provider="gcp-project",
                granted_permissions=project_granted,
                blockers=project_blockers,
                cleanup=(
                    CleanupStatus.CLEAN if not project_blockers else CleanupStatus.NOT_CREATED
                ),
                seed=iam.evidence,
                authority=gcp_project_authority(context, iam),
            )
        ),
        make_provider(
            ProviderFacts(
                provider="gcp-billing",
                granted_permissions=billing_granted,
                blockers=billing_blockers,
                cleanup=(
                    CleanupStatus.CLEAN if not billing_blockers else CleanupStatus.NOT_CREATED
                ),
                seed=iam.evidence,
                authority=gcp_billing_authority(context, iam),
            )
        ),
    )
