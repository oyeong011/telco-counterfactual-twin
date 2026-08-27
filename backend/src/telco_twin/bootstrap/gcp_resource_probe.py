"""Reversible GCP topic, budget, and deny-condition authority probes."""

from __future__ import annotations

from dataclasses import dataclass

from telco_twin.bootstrap.gcp_commands import (
    GcpContext,
    ProvisioningError,
    attempt_gcloud,
    require_gcloud,
)


@dataclass(frozen=True, slots=True)
class TemporaryProbeResult:
    """Cleanup proof for the resources created by this probe."""

    cleanup_complete: bool
    restored_bindings: bool
    schema_version: str


def _require_budget_name(name: str) -> None:
    if not name.startswith("billingAccounts/"):
        code = "invalid-budget-resource-name"
        raise ProvisioningError(code)


def _require_publisher_edge(policy: str) -> None:
    if "roles/pubsub.publisher" not in policy:
        code = "billing-publisher-edge-missing"
        raise ProvisioningError(code)


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
    cleanup_failures: list[str] = []
    failure: ProvisioningError | None = None
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
        _require_budget_name(budget_name)
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
        _require_publisher_edge(policy)
    except ProvisioningError as error:
        failure = error
    finally:
        if budget_name and not attempt_gcloud(
            ("gcloud", "billing", "budgets", "delete", budget_name, "--quiet")
        ):
            cleanup_failures.append("budget")
        if binding_created and not attempt_gcloud(
            (
                "gcloud",
                "iam",
                "service-accounts",
                "remove-iam-policy-binding",
                service_account,
                "--role=roles/iam.workloadIdentityUser",
                f"--member={deny_member}",
                "--quiet",
            )
        ):
            cleanup_failures.append("deny-binding")
        if provider_created and not attempt_gcloud(
            (
                "gcloud",
                "iam",
                "workload-identity-pools",
                "providers",
                "delete",
                deny_provider,
                f"--project={context.project_id}",
                "--location=global",
                "--workload-identity-pool=github-actions",
                "--quiet",
            )
        ):
            cleanup_failures.append("deny-provider")
        if topic_created and not attempt_gcloud(
            (
                "gcloud",
                "pubsub",
                "topics",
                "delete",
                topic,
                f"--project={context.project_id}",
                "--quiet",
            )
        ):
            cleanup_failures.append("topic")
    if cleanup_failures:
        code = "cleanup-incomplete"
        raise ProvisioningError(code)
    if failure is not None:
        raise failure
    return TemporaryProbeResult(
        cleanup_complete=True,
        restored_bindings=True,
        schema_version="1.0",
    )
