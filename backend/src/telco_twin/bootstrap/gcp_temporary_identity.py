"""Transactional temporary WIF provider and IAM-binding mutations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from telco_twin.bootstrap.gcp_binding import BindingRollbackIntent, prepare_binding_intent
from telco_twin.bootstrap.gcp_commands import ProvisioningError
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

if TYPE_CHECKING:
    from telco_twin.bootstrap.gcp_operation import GcpOperation


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
    operation: GcpOperation,
    provider_id: str,
    condition: str,
) -> ProviderRollbackIntent:
    """Prove exact provider absence before registering rollback ownership."""
    intent = ProviderRollbackIntent(
        operation.context,
        provider_id,
        condition,
        operation.ownership,
        operation.policy,
    )
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
        description=intent.ownership.marker,
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


def prepare_binding(
    service_account: str,
    member: str,
    operation: GcpOperation,
) -> BindingRollbackIntent:
    """Snapshot exact IAM state and prove the temporary member is absent."""
    intent = prepare_binding_intent(
        service_account,
        member,
        operation,
    )
    if intent is None:
        code = "deny-binding-conflict"
        raise ProvisioningError(code)
    return intent


def create_binding(
    snapshot: BindingRollbackIntent,
    member: str,
) -> None:
    """Add and read back the exact member after any command result."""
    if member != snapshot.member:
        code = "deny-binding-member-mismatch"
        raise ProvisioningError(code)
    snapshot.add()
