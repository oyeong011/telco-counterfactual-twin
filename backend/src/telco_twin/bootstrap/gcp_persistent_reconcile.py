"""Bounded read-back reconciliation for persistent GCP WIF mutations."""

from __future__ import annotations

from pydantic import TypeAdapter, ValidationError

from telco_twin.bootstrap import gcp_commands
from telco_twin.bootstrap.gcp_commands import GcpContext, ProvisioningError
from telco_twin.bootstrap.gcp_iam_contract import parse_iam_policy
from telco_twin.bootstrap.gcp_persistent_contract import (
    POOL_ID,
    PROVIDER_ID,
    PoolRollbackIntent,
    PoolSnapshot,
    ProviderConfig,
    ProviderSnapshot,
    provider_command,
)

POOL_LIST_ADAPTER = TypeAdapter(tuple[PoolSnapshot, ...])
WIF_ROLE = "roles/iam.workloadIdentityUser"


def _pool_list(intent: PoolRollbackIntent) -> tuple[PoolSnapshot, ...] | None:
    result = gcp_commands.run_gcloud(
        (
            "gcloud",
            "iam",
            "workload-identity-pools",
            "list",
            f"--project={intent.context.project_id}",
            "--location=global",
            f"--filter=name={intent.resource_name}",
            "--format=json",
        )
    )
    if result.returncode != 0:
        return None
    try:
        return POOL_LIST_ADAPTER.validate_json(result.stdout)
    except ValidationError:
        return None


def prepare_pool(context: GcpContext) -> PoolRollbackIntent:
    """Prove exact pool absence before registering rollback ownership."""
    intent = PoolRollbackIntent(context)
    snapshots = _pool_list(intent)
    if snapshots is None:
        code = "wif-pool-list-failed"
        raise ProvisioningError(code)
    if snapshots:
        code = "wif-pool-name-conflict"
        raise ProvisioningError(code)
    return intent


def verify_pool(intent: PoolRollbackIntent) -> bool:
    """Read back the exact created pool fingerprint."""
    snapshots = _pool_list(intent)
    return snapshots is not None and len(snapshots) == 1 and intent.matches(snapshots[0])


def cleanup_pool(intent: PoolRollbackIntent) -> bool:
    """Delete only the exact pool and verify its absence after any result."""
    before = _pool_list(intent)
    if before is None:
        return False
    if not before:
        return True
    if len(before) != 1 or not intent.matches(before[0]):
        return False
    _ = gcp_commands.run_gcloud(
        (
            "gcloud",
            "iam",
            "workload-identity-pools",
            "delete",
            POOL_ID,
            f"--project={intent.context.project_id}",
            "--location=global",
            "--quiet",
        )
    )
    after = _pool_list(intent)
    return after == ()


def read_provider(context: GcpContext) -> ProviderSnapshot | None:
    """Read the exact persistent provider or return no proven snapshot."""
    result = gcp_commands.run_gcloud(
        (
            "gcloud",
            "iam",
            "workload-identity-pools",
            "providers",
            "describe",
            PROVIDER_ID,
            f"--project={context.project_id}",
            "--location=global",
            f"--workload-identity-pool={POOL_ID}",
            "--format=json",
        )
    )
    if result.returncode != 0:
        return None
    try:
        return ProviderSnapshot.model_validate_json(result.stdout)
    except ValidationError:
        return None


def restore_provider(
    context: GcpContext,
    target: ProviderConfig,
    original: ProviderSnapshot,
) -> bool:
    """Restore only target/unchanged states and verify the exact old snapshot."""
    current = read_provider(context)
    if current is None:
        return False
    if current == original:
        return True
    if not current.matches(target):
        return False
    mapping = ",".join(f"{key}={value}" for key, value in sorted(original.mapping.items()))
    old_config = ProviderConfig(
        context=context,
        provider_id=PROVIDER_ID,
        issuer=original.issuer,
        mapping=mapping,
        condition=original.condition,
    )
    _ = gcp_commands.run_gcloud(provider_command("update-oidc", old_config))
    restored = read_provider(context)
    return restored == original


def binding_present(service_account: str, member: str) -> bool | None:
    """Read whether the exact member/role edge currently exists."""
    result = gcp_commands.run_gcloud(
        (
            "gcloud",
            "iam",
            "service-accounts",
            "get-iam-policy",
            service_account,
            "--format=json",
        )
    )
    if result.returncode != 0:
        return None
    try:
        policy = parse_iam_policy(result.stdout)
    except ProvisioningError:
        return None
    return any(
        binding.role == WIF_ROLE and member in binding.members for binding in policy.bindings
    )


def ensure_binding(service_account: str, member: str) -> None:
    """Add an absent binding and reconcile it after any command result."""
    before = binding_present(service_account, member)
    if before is None:
        code = "wif-binding-snapshot-failed"
        raise ProvisioningError(code)
    if before:
        return
    result = gcp_commands.run_gcloud(
        (
            "gcloud",
            "iam",
            "service-accounts",
            "add-iam-policy-binding",
            service_account,
            f"--role={WIF_ROLE}",
            f"--member={member}",
            "--quiet",
        )
    )
    after = binding_present(service_account, member)
    if result.returncode != 0:
        code = "wif-binding-write-failed"
        raise ProvisioningError(code)
    if after is not True:
        code = "wif-binding-reconcile-failed"
        raise ProvisioningError(code)
