"""Persistent WIF state creation, update, snapshot, and rollback."""

from __future__ import annotations

from pydantic import ValidationError

from telco_twin.bootstrap.gcp_commands import (
    GcpContext,
    ProvisioningError,
    require_gcloud,
    run_gcloud,
)
from telco_twin.bootstrap.gcp_persistent_contract import (
    ISSUER,
    MAPPING,
    POOL_ID,
    PROVIDER_ID,
    REPOSITORIES,
    PersistentState,
    ProviderConfig,
    ProviderSnapshot,
    provider_command,
)
from telco_twin.bootstrap.gcp_rollback import restore_persistent
from telco_twin.bootstrap.gcp_service_account import ensure_service_account


def _condition(owner_id: str) -> str:
    return (
        f"assertion.repository_owner_id=='{owner_id}' && assertion.repository in "
        "['oyeong011/telco-counterfactual-twin','oyeong011/mcp-evidence-plane']"
    )


def _principal(context: GcpContext, repository: str) -> str:
    return (
        "principalSet://iam.googleapis.com/projects/"
        f"{context.project_number}/locations/global/workloadIdentityPools/{POOL_ID}/"
        f"attribute.repository/{repository}"
    )


def ensure_persistent(context: GcpContext) -> PersistentState:
    """Create or update exact WIF state after taking rollback snapshots."""
    service_account_state = ensure_service_account(context)
    service_account = service_account_state.service_account
    pool_args = (
        "gcloud",
        "iam",
        "workload-identity-pools",
        "describe",
        POOL_ID,
        f"--project={context.project_id}",
        "--location=global",
    )
    pool_created = run_gcloud(pool_args).returncode != 0
    state = PersistentState(
        service_account_state=service_account_state,
        pool_created=pool_created,
        provider_created=False,
        provider_snapshot=None,
    )
    try:
        if pool_created:
            _ = require_gcloud(
                (
                    "gcloud",
                    "iam",
                    "workload-identity-pools",
                    "create",
                    POOL_ID,
                    f"--project={context.project_id}",
                    "--location=global",
                    "--display-name=GitHub Actions",
                    "--quiet",
                ),
                "wif-pool-create-failed",
            )
        provider_before = run_gcloud(
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
        provider_created = provider_before.returncode != 0
        state = PersistentState(
            service_account_state=service_account_state,
            pool_created=pool_created,
            provider_created=provider_created,
            provider_snapshot=None,
        )
        snapshot: ProviderSnapshot | None = None
        if not provider_created:
            try:
                snapshot = ProviderSnapshot.model_validate_json(provider_before.stdout)
            except ValidationError:
                code = "provider-snapshot-invalid"
                raise ProvisioningError(code) from None
            state = PersistentState(
                service_account_state=service_account_state,
                pool_created=pool_created,
                provider_created=False,
                provider_snapshot=snapshot,
            )
        config = ProviderConfig(
            context=context,
            provider_id=PROVIDER_ID,
            issuer=ISSUER,
            mapping=MAPPING,
            condition=_condition(context.owner_id),
        )
        action = "create-oidc" if provider_created else "update-oidc"
        _ = require_gcloud(
            provider_command(action, config),
            "wif-provider-write-failed",
        )
        for repository in REPOSITORIES:
            _ = require_gcloud(
                (
                    "gcloud",
                    "iam",
                    "service-accounts",
                    "add-iam-policy-binding",
                    service_account,
                    "--role=roles/iam.workloadIdentityUser",
                    f"--member={_principal(context, repository)}",
                    "--quiet",
                ),
                "wif-binding-write-failed",
            )
    except ProvisioningError:
        if not restore_persistent(context, state):
            code = "persistent-rollback-failed"
            raise ProvisioningError(code) from None
        raise
    return state
