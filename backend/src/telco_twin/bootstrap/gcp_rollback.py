"""Rollback of persistent WIF and service-account state."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from telco_twin.bootstrap.gcp_commands import GcpContext, attempt_gcloud
from telco_twin.bootstrap.gcp_persistent import (
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
    if state.service_account_created:
        restored &= attempt_gcloud(
            (
                "gcloud",
                "iam",
                "service-accounts",
                "delete",
                state.service_account,
                "--quiet",
            )
        )
    else:
        with TemporaryDirectory(prefix="twin-wif-rollback-") as temp_dir:
            policy_path = Path(temp_dir) / "policy.json"
            _ = policy_path.write_text(state.iam_policy, encoding="utf-8")
            restored &= attempt_gcloud(
                (
                    "gcloud",
                    "iam",
                    "service-accounts",
                    "set-iam-policy",
                    state.service_account,
                    str(policy_path),
                )
            )
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
