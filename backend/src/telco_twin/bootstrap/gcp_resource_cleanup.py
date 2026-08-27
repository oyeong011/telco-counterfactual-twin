"""Finally-safe cleanup for temporary GCP preflight resources."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from telco_twin.bootstrap.gcp_commands import GcpContext, attempt_gcloud

if TYPE_CHECKING:
    from telco_twin.bootstrap.gcp_resource_contract import BudgetCleanupTarget


@dataclass(frozen=True, slots=True)
class TemporaryCleanupPlan:
    """Exact temporary resources and binding that may require cleanup."""

    context: GcpContext
    service_account: str
    budget: BudgetCleanupTarget | None
    binding_created: bool
    deny_member: str
    provider_created: bool
    deny_provider: str
    topic_created: bool
    topic: str


def cleanup_temporary(plan: TemporaryCleanupPlan) -> tuple[str, ...]:
    """Remove every created temporary resource and return stable failure labels."""
    failures: list[str] = []
    if plan.budget is not None:
        if not plan.budget.is_owned_by(plan.context, plan.topic):
            failures.append("budget-ownership")
        elif not attempt_gcloud(
            (
                "gcloud",
                "billing",
                "budgets",
                "delete",
                plan.budget.resource_name,
                "--quiet",
            )
        ):
            failures.append("budget")
    if plan.binding_created and not attempt_gcloud(
        (
            "gcloud",
            "iam",
            "service-accounts",
            "remove-iam-policy-binding",
            plan.service_account,
            "--role=roles/iam.workloadIdentityUser",
            f"--member={plan.deny_member}",
            "--quiet",
        )
    ):
        failures.append("deny-binding")
    if plan.provider_created and not attempt_gcloud(
        (
            "gcloud",
            "iam",
            "workload-identity-pools",
            "providers",
            "delete",
            plan.deny_provider,
            f"--project={plan.context.project_id}",
            "--location=global",
            "--workload-identity-pool=github-actions",
            "--quiet",
        )
    ):
        failures.append("deny-provider")
    if plan.topic_created and not attempt_gcloud(
        (
            "gcloud",
            "pubsub",
            "topics",
            "delete",
            plan.topic,
            f"--project={plan.context.project_id}",
            "--quiet",
        )
    ):
        failures.append("topic")
    return tuple(failures)
