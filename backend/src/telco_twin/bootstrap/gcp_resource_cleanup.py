"""Finally-safe cleanup for temporary GCP preflight resources."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from telco_twin.bootstrap.gcp_temporary_mutations import (
    cleanup_budget,
    cleanup_provider,
    cleanup_topic,
)

if TYPE_CHECKING:
    from telco_twin.bootstrap.gcp_resource_contract import (
        BudgetRollbackIntent,
        ProviderRollbackIntent,
        TopicRollbackIntent,
    )
    from telco_twin.bootstrap.gcp_service_account import ExistingServiceAccountSnapshot


@dataclass(frozen=True, slots=True)
class TemporaryCleanupPlan:
    """Exact temporary resources and binding that may require cleanup."""

    budget: BudgetRollbackIntent | None
    binding: ExistingServiceAccountSnapshot | None
    provider: ProviderRollbackIntent | None
    topic: TopicRollbackIntent | None


def cleanup_temporary(plan: TemporaryCleanupPlan) -> tuple[str, ...]:
    """Remove every created temporary resource and return stable failure labels."""
    failures: list[str] = []
    if plan.budget is not None and not cleanup_budget(plan.budget):
        failures.append("budget")
    if plan.binding is not None and not plan.binding.rollback():
        failures.append("deny-binding")
    if plan.provider is not None and not cleanup_provider(plan.provider):
        failures.append("deny-provider")
    if plan.topic is not None and not cleanup_topic(plan.topic):
        failures.append("topic")
    return tuple(failures)
