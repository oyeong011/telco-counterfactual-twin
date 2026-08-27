"""Persistent WIF state creation, update, snapshot, and rollback."""

from __future__ import annotations

from pydantic import ValidationError

from telco_twin.bootstrap.gcp_commands import (
    GcpContext,
    ProvisioningError,
    run_gcloud,
)
from telco_twin.bootstrap.gcp_persistent_contract import (
    ISSUER,
    MAPPING,
    POOL_ID,
    PROVIDER_ID,
    REPOSITORIES,
    PersistentState,
    PoolRollbackIntent,
    ProviderConfig,
    ProviderSnapshot,
    provider_command,
)
from telco_twin.bootstrap.gcp_persistent_reconcile import (
    ensure_binding,
    prepare_pool,
    read_provider,
    verify_pool,
)
from telco_twin.bootstrap.gcp_rollback import restore_persistent
from telco_twin.bootstrap.gcp_service_account import ensure_service_account
from telco_twin.bootstrap.gcp_temporary_mutations import prepare_provider


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


def _write_pool(context: GcpContext, intent: PoolRollbackIntent) -> None:
    result = run_gcloud(
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
        )
    )
    verified = verify_pool(intent)
    if result.returncode != 0:
        code = "wif-pool-create-failed"
        raise ProvisioningError(code)
    if not verified:
        code = "wif-pool-reconcile-failed"
        raise ProvisioningError(code)


def _provider_prior(
    context: GcpContext,
    config: ProviderConfig,
) -> tuple[ProviderConfig | None, ProviderSnapshot | None]:
    before = run_gcloud(
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
    if before.returncode != 0:
        _ = prepare_provider(context, PROVIDER_ID, config.condition)
        return config, None
    try:
        return None, ProviderSnapshot.model_validate_json(before.stdout)
    except ValidationError:
        code = "provider-snapshot-invalid"
        raise ProvisioningError(code) from None


def _write_provider(config: ProviderConfig, *, create: bool) -> None:
    action = "create-oidc" if create else "update-oidc"
    result = run_gcloud(provider_command(action, config))
    current = read_provider(config.context)
    if result.returncode != 0:
        code = "wif-provider-write-failed"
        raise ProvisioningError(code)
    if current is None or not current.matches(config):
        code = "wif-provider-reconcile-failed"
        raise ProvisioningError(code)


def ensure_persistent(context: GcpContext) -> PersistentState:
    """Create or update exact WIF state after taking rollback snapshots."""
    service_account_state = ensure_service_account(context)
    service_account = service_account_state.service_account
    state = PersistentState(
        service_account_state=service_account_state,
        pool_intent=None,
        provider_create_intent=None,
        provider_target=None,
        provider_snapshot=None,
    )
    pool_before = run_gcloud(
        (
            "gcloud",
            "iam",
            "workload-identity-pools",
            "describe",
            POOL_ID,
            f"--project={context.project_id}",
            "--location=global",
        )
    )
    try:
        pool_intent = prepare_pool(context) if pool_before.returncode != 0 else None
        state = PersistentState(
            service_account_state=service_account_state,
            pool_intent=pool_intent,
            provider_create_intent=None,
            provider_target=None,
            provider_snapshot=None,
        )
        if pool_intent is not None:
            _write_pool(context, pool_intent)
        config = ProviderConfig(
            context=context,
            provider_id=PROVIDER_ID,
            issuer=ISSUER,
            mapping=MAPPING,
            condition=_condition(context.owner_id),
        )
        create_intent, snapshot = _provider_prior(context, config)
        state = PersistentState(
            service_account_state=service_account_state,
            pool_intent=state.pool_intent,
            provider_create_intent=create_intent,
            provider_target=config,
            provider_snapshot=snapshot,
        )
        _write_provider(config, create=create_intent is not None)
        for repository in REPOSITORIES:
            ensure_binding(service_account, _principal(context, repository))
    except ProvisioningError:
        if not restore_persistent(context, state):
            code = "persistent-rollback-failed"
            raise ProvisioningError(code) from None
        raise
    return state
