"""Reversible GCP topic, budget, and deny-condition authority probes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

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
    parse_budget,
    parse_publisher_policy,
    require_budget_name,
)
from telco_twin.bootstrap.github_deny_probe import assert_deny_exchange
from telco_twin.bootstrap.preflight_contract import receipt_for
from telco_twin.bootstrap.probe_errors import ProviderProbeError


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


def _provider_command(
    context: GcpContext,
    provider_id: str,
    condition: str,
) -> tuple[str, ...]:
    mapping = (
        "google.subject=assertion.sub,"
        "attribute.repository=assertion.repository,"
        "attribute.repository_owner_id=assertion.repository_owner_id"
    )
    return (
        "gcloud",
        "iam",
        "workload-identity-pools",
        "providers",
        "create-oidc",
        provider_id,
        f"--project={context.project_id}",
        "--location=global",
        "--workload-identity-pool=github-actions",
        "--issuer-uri=https://token.actions.githubusercontent.com",
        f"--attribute-mapping={mapping}",
        f"--attribute-condition={condition}",
        "--quiet",
    )


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
    budget_name = ""
    provider_created = False
    binding_created = False
    topic_created = False
    failure: ProvisioningError | None = None
    deny_exchange_evidence = ""
    publisher_policy_evidence = ""
    budget_schema_version: Literal["1.0"] | None = None
    try:
        _ = require_gcloud(
            _provider_command(
                context,
                deny_provider,
                "assertion.repository=='oyeong011/nonmatching-preflight'",
            ),
            "deny-provider-create-failed",
        )
        provider_created = True
        _ = require_gcloud(
            (
                "gcloud",
                "iam",
                "service-accounts",
                "add-iam-policy-binding",
                service_account,
                "--role=roles/iam.workloadIdentityUser",
                f"--member={deny_member}",
                "--quiet",
            ),
            "deny-binding-create-failed",
        )
        binding_created = True
        provider_resource = (
            f"projects/{context.project_number}/locations/global/workloadIdentityPools/"
            f"github-actions/providers/{deny_provider}"
        )
        try:
            deny_receipt = assert_deny_exchange(
                provider_resource,
                service_account,
                context.project_id,
            )
        except ProviderProbeError as error:
            raise ProvisioningError(error.code) from None
        deny_exchange_evidence = deny_receipt.evidence
        _ = require_gcloud(
            (
                "gcloud",
                "pubsub",
                "topics",
                "create",
                topic,
                f"--project={context.project_id}",
            ),
            "topic-create-failed",
        )
        topic_created = True
        budget_name = require_gcloud(
            (
                "gcloud",
                "billing",
                "budgets",
                "create",
                f"--billing-account={context.billing_account_id}",
                f"--display-name={topic}",
                "--budget-amount=1USD",
                f"--notifications-rule-pubsub-topic=projects/{context.project_id}/topics/{topic}",
                f"--filter-projects=projects/{context.project_number}",
                "--format=value(name)",
            ),
            "budget-create-failed",
        )
        require_budget_name(budget_name)
        budget_snapshot = require_gcloud(
            (
                "gcloud",
                "billing",
                "budgets",
                "describe",
                budget_name,
                "--format=json",
            ),
            "budget-describe-failed",
        )
        budget = parse_budget(budget_snapshot, budget_name)
        budget_schema_version = budget.notifications_rule.schema_version
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
                context=context,
                service_account=service_account,
                budget_name=budget_name,
                binding_created=binding_created,
                deny_member=deny_member,
                provider_created=provider_created,
                deny_provider=deny_provider,
                topic_created=topic_created,
                topic=topic,
            )
        )
    if cleanup_failures:
        code = "cleanup-incomplete"
        raise ProvisioningError(code)
    if failure is not None:
        raise failure
    if (
        budget_schema_version is None
        or not budget_name
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
        budget_resource=budget_name,
        publisher_policy_evidence=publisher_policy_evidence,
        deny_exchange_evidence=deny_exchange_evidence,
    )
