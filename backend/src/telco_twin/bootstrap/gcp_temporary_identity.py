"""Transactional temporary WIF provider and IAM-binding mutations."""

from __future__ import annotations

from telco_twin.bootstrap import gcp_commands
from telco_twin.bootstrap.gcp_commands import GcpContext, ProvisioningError
from telco_twin.bootstrap.gcp_iam_contract import parse_iam_policy
from telco_twin.bootstrap.gcp_persistent_contract import (
    ISSUER,
    MAPPING,
    ProviderConfig,
    provider_command,
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
    result = gcp_commands.run_gcloud(
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
) -> ProviderRollbackIntent:
    """Prove exact provider absence before registering rollback ownership."""
    intent = ProviderRollbackIntent(context, provider_id, condition)
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
    result = gcp_commands.run_gcloud(provider_command("create-oidc", config))
    snapshots = _provider_list(intent)
    matches = tuple(snapshot for snapshot in snapshots if intent.matches(snapshot))
    if result.returncode != 0:
        code = "deny-provider-create-failed"
        raise ProvisioningError(code)
    if len(snapshots) != 1 or len(matches) != 1:
        code = "deny-provider-reconcile-failed"
        raise ProvisioningError(code)


def cleanup_provider(intent: ProviderRollbackIntent) -> bool:
    """Delete only the exact provider owned by the registered intent."""
    try:
        snapshots = _provider_list(intent)
    except ProvisioningError:
        return False
    if not snapshots:
        return True
    if len(snapshots) != 1 or not intent.matches(snapshots[0]):
        return False
    _ = gcp_commands.run_gcloud(
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
        return _provider_list(intent) == ()
    except ProvisioningError:
        return False


def _binding_present(policy: str, member: str) -> bool:
    parsed = parse_iam_policy(policy)
    return any(
        binding.role == WIF_ROLE and member in binding.members for binding in parsed.bindings
    )


def prepare_binding(service_account: str, member: str) -> ExistingServiceAccountSnapshot:
    """Snapshot exact IAM state and prove the temporary member is absent."""
    policy = gcp_commands.require_gcloud(
        (
            "gcloud",
            "iam",
            "service-accounts",
            "get-iam-policy",
            service_account,
            "--format=json",
        ),
        "deny-binding-snapshot-failed",
    )
    if _binding_present(policy, member):
        code = "deny-binding-conflict"
        raise ProvisioningError(code)
    return ExistingServiceAccountSnapshot(service_account, policy)


def create_binding(
    snapshot: ExistingServiceAccountSnapshot,
    member: str,
) -> None:
    """Add and read back the exact member after any command result."""
    result = gcp_commands.run_gcloud(
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
    current = gcp_commands.require_gcloud(
        (
            "gcloud",
            "iam",
            "service-accounts",
            "get-iam-policy",
            snapshot.service_account,
            "--format=json",
        ),
        "deny-binding-reconcile-failed",
    )
    if result.returncode != 0:
        code = "deny-binding-create-failed"
        raise ProvisioningError(code)
    if not _binding_present(current, member):
        code = "deny-binding-reconcile-failed"
        raise ProvisioningError(code)
