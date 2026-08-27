"""Rollback of persistent WIF and service-account state."""

from __future__ import annotations

from telco_twin.bootstrap.gcp_commands import GcpContext, attempt_gcloud
from telco_twin.bootstrap.gcp_persistent_contract import (
    POOL_ID,
    PROVIDER_ID,
    PersistentState,
    ProviderConfig,
    provider_command,
)


def restore_persistent(context: GcpContext, state: PersistentState) -> bool:
    """Restore exact provider/IAM snapshots after a downstream probe failure."""
    restored = True
    if state.provider_created:
        restored &= attempt_gcloud(
            (
                "gcloud",
                "iam",
                "workload-identity-pools",
                "providers",
                "delete",
                PROVIDER_ID,
                f"--project={context.project_id}",
                "--location=global",
                f"--workload-identity-pool={POOL_ID}",
                "--quiet",
            )
        )
    elif state.provider_snapshot is not None:
        mapping = ",".join(
            f"{key}={value}" for key, value in sorted(state.provider_snapshot.mapping.items())
        )
        old_config = ProviderConfig(
            context=context,
            provider_id=PROVIDER_ID,
            issuer=state.provider_snapshot.issuer,
            mapping=mapping,
            condition=state.provider_snapshot.condition,
        )
        restored &= attempt_gcloud(provider_command("update-oidc", old_config))
    restored &= state.service_account_state.rollback()
    if state.pool_created:
        restored &= attempt_gcloud(
            (
                "gcloud",
                "iam",
                "workload-identity-pools",
                "delete",
                POOL_ID,
                f"--project={context.project_id}",
                "--location=global",
                "--quiet",
            )
        )
    return restored
