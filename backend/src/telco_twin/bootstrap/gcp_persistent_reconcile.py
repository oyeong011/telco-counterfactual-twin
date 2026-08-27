"""Bounded read-back reconciliation for persistent GCP WIF mutations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import TypeAdapter, ValidationError

from telco_twin.bootstrap.gcp_binding import BindingRollbackIntent, prepare_binding_intent
from telco_twin.bootstrap.gcp_commands import GcpContext, ProvisioningError
from telco_twin.bootstrap.gcp_persistent_contract import (
    POOL_ID,
    PROVIDER_ID,
    PoolRollbackIntent,
    PoolSnapshot,
    ProviderConfig,
    ProviderSnapshot,
    provider_command,
)

if TYPE_CHECKING:
    from telco_twin.bootstrap.gcp_operation import GcpOperation
    from telco_twin.bootstrap.gcp_reconciliation import ReconciliationPolicy

POOL_LIST_ADAPTER = TypeAdapter(tuple[PoolSnapshot, ...])


def _pool_list(intent: PoolRollbackIntent) -> tuple[PoolSnapshot, ...] | None:
    result = intent.policy.read(
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


def prepare_pool(
    operation: GcpOperation,
) -> PoolRollbackIntent:
    """Prove exact pool absence before registering rollback ownership."""
    intent = PoolRollbackIntent(
        operation.context,
        operation.ownership,
        operation.policy,
    )
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
    visible = intent.policy.poll(
        lambda: _pool_list(intent),
        lambda snapshots: (
            snapshots is not None and len(snapshots) == 1 and intent.matches(snapshots[0])
        ),
    )
    return visible is not None


def cleanup_pool(intent: PoolRollbackIntent) -> bool:
    """Delete only the exact pool and verify its absence after any result."""
    visible = intent.policy.poll(
        lambda: _pool_list(intent),
        lambda snapshots: (
            snapshots is not None and len(snapshots) == 1 and intent.matches(snapshots[0])
        ),
    )
    if visible is None:
        return False
    _ = intent.policy.read(
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
    absent = intent.policy.poll(
        lambda: _pool_list(intent),
        lambda snapshots: snapshots == (),
        confirmations=2,
    )
    return absent is not None


def read_provider(
    context: GcpContext,
    policy: ReconciliationPolicy,
) -> ProviderSnapshot | None:
    """Read the exact persistent provider or return no proven snapshot."""
    result = policy.read(
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
    policy: ReconciliationPolicy,
) -> bool:
    """Restore only target/unchanged states and verify the exact old snapshot."""
    visible = policy.poll(
        lambda: read_provider(context, policy),
        lambda current: current is not None and current.matches(target),
    )
    if visible is None:
        return False
    mapping = ",".join(f"{key}={value}" for key, value in sorted(original.mapping.items()))
    old_config = ProviderConfig(
        context=context,
        provider_id=PROVIDER_ID,
        issuer=original.issuer,
        mapping=mapping,
        condition=original.condition,
        description=original.description,
    )
    _ = policy.read(provider_command("update-oidc", old_config))
    restored = policy.poll(
        lambda: read_provider(context, policy),
        lambda current: current == original,
        confirmations=2,
    )
    return restored is not None


def prepare_persistent_binding(
    service_account: str,
    member: str,
    operation: GcpOperation,
) -> BindingRollbackIntent | None:
    """Capture prior IAM state unless the stable member already exists."""
    return prepare_binding_intent(service_account, member, operation)


def ensure_binding(
    intent: BindingRollbackIntent,
) -> None:
    """Write an operation-owned binding after its rollback is registered."""
    intent.add()
