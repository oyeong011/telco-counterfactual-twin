"""Bounded read-back reconciliation for persistent GCP WIF mutations."""

from __future__ import annotations

from pydantic import TypeAdapter, ValidationError

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
from telco_twin.bootstrap.gcp_reconciliation import (
    DEFAULT_RECONCILIATION_POLICY,
    ReconciliationPolicy,
)

POOL_LIST_ADAPTER = TypeAdapter(tuple[PoolSnapshot, ...])
WIF_ROLE = "roles/iam.workloadIdentityUser"


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
    context: GcpContext,
    policy: ReconciliationPolicy = DEFAULT_RECONCILIATION_POLICY,
) -> PoolRollbackIntent:
    """Prove exact pool absence before registering rollback ownership."""
    intent = PoolRollbackIntent(context, policy)
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
    )
    _ = policy.read(provider_command("update-oidc", old_config))
    restored = policy.poll(
        lambda: read_provider(context, policy),
        lambda current: current == original,
        confirmations=2,
    )
    return restored is not None


def binding_present(
    service_account: str,
    member: str,
    policy: ReconciliationPolicy,
) -> bool | None:
    """Read whether the exact member/role edge currently exists."""
    result = policy.read(
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
        parsed_policy = parse_iam_policy(result.stdout)
    except ProvisioningError:
        return None
    return any(
        binding.role == WIF_ROLE and member in binding.members for binding in parsed_policy.bindings
    )


def ensure_binding(
    service_account: str,
    member: str,
    policy: ReconciliationPolicy,
) -> None:
    """Add an absent binding and reconcile it after any command result."""
    before = binding_present(service_account, member, policy)
    if before is None:
        code = "wif-binding-snapshot-failed"
        raise ProvisioningError(code)
    if before:
        return
    result = policy.read(
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
    after = policy.poll(
        lambda: binding_present(service_account, member, policy),
        lambda present: present is True,
    )
    if result.returncode != 0:
        code = "wif-binding-write-failed"
        raise ProvisioningError(code)
    if after is None:
        code = "wif-binding-reconcile-failed"
        raise ProvisioningError(code)
