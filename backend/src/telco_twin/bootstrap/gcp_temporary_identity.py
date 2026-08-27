"""Transactional temporary WIF provider and IAM-binding mutations."""

from __future__ import annotations

from telco_twin.bootstrap.gcp_commands import GcpContext, ProvisioningError
from telco_twin.bootstrap.gcp_iam_contract import parse_iam_policy
from telco_twin.bootstrap.gcp_persistent_contract import (
    ISSUER,
    MAPPING,
    ProviderConfig,
    provider_command,
)
from telco_twin.bootstrap.gcp_reconciliation import (
    DEFAULT_RECONCILIATION_POLICY,
    ReconciliationPolicy,
)
from telco_twin.bootstrap.gcp_resource_contract import (
    ProviderRollbackIntent,
    TemporaryProviderSnapshot,
    parse_provider_list,
)
from telco_twin.bootstrap.gcp_service_account import ExistingServiceAccountSnapshot

WIF_ROLE = "roles/iam.workloadIdentityUser"


def _provider_list(
    intent: ProviderRollbackIntent,
) -> tuple[TemporaryProviderSnapshot, ...]:
    result = intent.policy.read(
        (
            "gcloud",
            "iam",
            "workload-identity-pools",
            "providers",
            "list",
            f"--project={intent.context.project_id}",
            "--location=global",
            "--workload-identity-pool=github-actions",
            f"--filter=name={intent.resource_name}",
            "--format=json",
        )
    )
    if result.returncode != 0:
        code = "deny-provider-reconcile-failed"
        raise ProvisioningError(code)
    return parse_provider_list(result.stdout)


def prepare_provider(
    context: GcpContext,
    provider_id: str,
    condition: str,
    policy: ReconciliationPolicy = DEFAULT_RECONCILIATION_POLICY,
) -> ProviderRollbackIntent:
    """Prove exact provider absence before registering rollback ownership."""
    intent = ProviderRollbackIntent(context, provider_id, condition, policy)
    if _provider_list(intent):
        code = "deny-provider-name-conflict"
        raise ProvisioningError(code)
    return intent


def create_provider(intent: ProviderRollbackIntent) -> None:
    """Create and read back the exact provider after any command result."""
    config = ProviderConfig(
        context=intent.context,
        provider_id=intent.provider_id,
        issuer=ISSUER,
        mapping=MAPPING,
        condition=intent.condition,
    )
    result = intent.policy.read(provider_command("create-oidc", config))
    visible = intent.policy.poll(
        lambda: _provider_list(intent),
        lambda snapshots: len(snapshots) == 1 and intent.matches(snapshots[0]),
    )
    if result.returncode != 0:
        code = "deny-provider-create-failed"
        raise ProvisioningError(code)
    if visible is None:
        code = "deny-provider-reconcile-failed"
        raise ProvisioningError(code)


def cleanup_provider(intent: ProviderRollbackIntent) -> bool:
    """Delete only the exact provider owned by the registered intent."""
    try:
        visible = intent.policy.poll(
            lambda: _provider_list(intent),
            lambda snapshots: len(snapshots) == 1 and intent.matches(snapshots[0]),
        )
    except ProvisioningError:
        return False
    if visible is None:
        return False
    _ = intent.policy.read(
        (
            "gcloud",
            "iam",
            "workload-identity-pools",
            "providers",
            "delete",
            intent.provider_id,
            f"--project={intent.context.project_id}",
            "--location=global",
            "--workload-identity-pool=github-actions",
            "--quiet",
        )
    )
    try:
        absent = intent.policy.poll(
            lambda: _provider_list(intent),
            lambda snapshots: snapshots == (),
            confirmations=2,
        )
    except ProvisioningError:
        return False
    return absent is not None


def _binding_present(policy: str, member: str) -> bool:
    parsed = parse_iam_policy(policy)
    return any(
        binding.role == WIF_ROLE and member in binding.members for binding in parsed.bindings
    )


def prepare_binding(
    service_account: str,
    member: str,
    policy: ReconciliationPolicy = DEFAULT_RECONCILIATION_POLICY,
) -> ExistingServiceAccountSnapshot:
    """Snapshot exact IAM state and prove the temporary member is absent."""
    policy_result = policy.read(
        (
            "gcloud",
            "iam",
            "service-accounts",
            "get-iam-policy",
            service_account,
            "--format=json",
        )
    )
    if policy_result.returncode != 0:
        code = "deny-binding-snapshot-failed"
        raise ProvisioningError(code)
    if _binding_present(policy_result.stdout, member):
        code = "deny-binding-conflict"
        raise ProvisioningError(code)
    return ExistingServiceAccountSnapshot(
        service_account,
        policy_result.stdout,
        policy,
        (member,),
    )


def create_binding(
    snapshot: ExistingServiceAccountSnapshot,
    member: str,
) -> None:
    """Add and read back the exact member after any command result."""
    result = snapshot.policy.read(
        (
            "gcloud",
            "iam",
            "service-accounts",
            "add-iam-policy-binding",
            snapshot.service_account,
            f"--role={WIF_ROLE}",
            f"--member={member}",
            "--quiet",
        )
    )
    current = snapshot.policy.poll(
        lambda: snapshot.policy.read(
            (
                "gcloud",
                "iam",
                "service-accounts",
                "get-iam-policy",
                snapshot.service_account,
                "--format=json",
            )
        ),
        lambda read_result: (
            read_result.returncode == 0 and _binding_present(read_result.stdout, member)
        ),
    )
    if result.returncode != 0:
        code = "deny-binding-create-failed"
        raise ProvisioningError(code)
    if current is None:
        code = "deny-binding-reconcile-failed"
        raise ProvisioningError(code)
