"""Reversible GCP topic, budget, and deny-condition authority probes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from telco_twin.bootstrap.gcp_commands import (
    GcpContext,
    ProvisioningError,
    require_gcloud,
)
from telco_twin.bootstrap.gcp_resource_cleanup import (
    TemporaryCleanupPlan,
    cleanup_temporary,
)
from telco_twin.bootstrap.gcp_resource_contract import (
    BudgetCleanupTarget,
    BudgetRollbackIntent,
    ProviderRollbackIntent,
    TopicRollbackIntent,
    parse_budget,
    parse_publisher_policy,
)
from telco_twin.bootstrap.gcp_temporary_mutations import (
    create_binding,
    create_budget,
    create_provider,
    create_topic,
    prepare_binding,
    prepare_budget,
    prepare_provider,
    prepare_topic,
)
from telco_twin.bootstrap.github_deny_probe import assert_deny_exchange
from telco_twin.bootstrap.preflight_contract import receipt_for
from telco_twin.bootstrap.probe_errors import ProviderProbeError

if TYPE_CHECKING:
    from telco_twin.bootstrap.gcp_service_account import ExistingServiceAccountSnapshot


@dataclass(frozen=True, slots=True)
class TemporaryProbeResult:
    """Cleanup proof for the resources created by this probe."""

    cleanup_complete: bool
    restored_bindings: bool
    budget_schema_version: Literal["1.0"]
    topic_resource: str
    budget_resource: str
    publisher_policy_evidence: str
    deny_exchange_evidence: str


def run_temporary_probes(
    context: GcpContext,
    service_account: str,
    suffix: str,
) -> TemporaryProbeResult:
    """Create authority probes and always remove their resources and IAM binding."""
    deny_provider = f"github-oidc-deny-{suffix}"
    topic = f"twin-preflight-{suffix}"
    deny_member = (
        "principalSet://iam.googleapis.com/projects/"
        f"{context.project_number}/locations/global/workloadIdentityPools/github-actions/"
        "attribute.repository/oyeong011/nonmatching-preflight"
    )
    budget_target: BudgetCleanupTarget | None = None
    budget_intent: BudgetRollbackIntent | None = None
    provider_intent: ProviderRollbackIntent | None = None
    binding_snapshot: ExistingServiceAccountSnapshot | None = None
    topic_intent: TopicRollbackIntent | None = None
    failure: ProvisioningError | None = None
    deny_exchange_evidence = ""
    publisher_policy_evidence = ""
    budget_schema_version: Literal["1.0"] | None = None
    try:
        provider_intent = prepare_provider(
            context,
            deny_provider,
            "assertion.repository=='oyeong011/nonmatching-preflight'",
        )
        create_provider(provider_intent)
        binding_snapshot = prepare_binding(service_account, deny_member)
        create_binding(binding_snapshot, deny_member)
        try:
            deny_receipt = assert_deny_exchange(
                provider_intent.resource_name,
                service_account,
                context.project_id,
            )
        except ProviderProbeError as error:
            raise ProvisioningError(error.code) from None
        deny_exchange_evidence = deny_receipt.evidence
        topic_intent = prepare_topic(context, topic)
        create_topic(topic_intent)
        budget_intent = prepare_budget(context, topic)
        budget_target = create_budget(budget_intent)
        budget_snapshot = require_gcloud(
            (
                "gcloud",
                "billing",
                "budgets",
                "describe",
                budget_target.resource_name,
                "--format=json",
            ),
            "budget-describe-failed",
        )
        _ = parse_budget(budget_snapshot, budget_target)
        budget_schema_version = "1.0"
        policy = require_gcloud(
            (
                "gcloud",
                "pubsub",
                "topics",
                "get-iam-policy",
                topic,
                f"--project={context.project_id}",
                "--format=json",
            ),
            "publisher-policy-read-failed",
        )
        parsed_policy = parse_publisher_policy(policy)
        publisher_policy_evidence = receipt_for(
            "billing-publisher-policy",
            f"projects/{context.project_id}/topics/{topic}",
            parsed_policy.model_dump_json(),
        )
    except ProvisioningError as error:
        failure = error
    finally:
        cleanup_failures = cleanup_temporary(
            TemporaryCleanupPlan(
                budget=budget_intent,
                binding=binding_snapshot,
                provider=provider_intent,
                topic=topic_intent,
            )
        )
    if cleanup_failures:
        code = "cleanup-incomplete"
        raise ProvisioningError(code)
    if failure is not None:
        raise failure
    if (
        budget_schema_version is None
        or budget_target is None
        or not publisher_policy_evidence
        or not deny_exchange_evidence
    ):
        code = "temporary-probe-receipt-incomplete"
        raise ProvisioningError(code)
    return TemporaryProbeResult(
        cleanup_complete=True,
        restored_bindings=True,
        budget_schema_version=budget_schema_version,
        topic_resource=f"projects/{context.project_id}/topics/{topic}",
        budget_resource=budget_target.resource_name,
        publisher_policy_evidence=publisher_policy_evidence,
        deny_exchange_evidence=deny_exchange_evidence,
    )
