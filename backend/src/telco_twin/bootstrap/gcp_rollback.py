"""Rollback of persistent WIF and service-account state."""

from __future__ import annotations

from typing import TYPE_CHECKING

from telco_twin.bootstrap.gcp_persistent_reconcile import cleanup_pool, restore_provider
from telco_twin.bootstrap.gcp_resource_contract import ProviderRollbackIntent
from telco_twin.bootstrap.gcp_temporary_mutations import cleanup_provider

if TYPE_CHECKING:
    from telco_twin.bootstrap.gcp_commands import GcpContext
    from telco_twin.bootstrap.gcp_persistent_contract import PersistentState


def restore_persistent(context: GcpContext, state: PersistentState) -> bool:
    """Restore exact provider/IAM snapshots after a downstream probe failure."""
    restored = True
    if state.provider_create_intent is not None:
        restored &= cleanup_provider(
            ProviderRollbackIntent(
                context=context,
                provider_id=state.provider_create_intent.provider_id,
                condition=state.provider_create_intent.condition,
                policy=state.policy,
            )
        )
    elif state.provider_snapshot is not None and state.provider_target is not None:
        restored &= restore_provider(
            context,
            state.provider_target,
            state.provider_snapshot,
            state.policy,
        )
    restored &= state.service_account_state.rollback()
    if state.pool_intent is not None:
        restored &= cleanup_pool(state.pool_intent)
    return restored
