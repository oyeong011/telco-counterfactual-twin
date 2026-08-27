"""Persistent WIF state creation, update, snapshot, and rollback."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Literal

from pydantic import AliasPath, BaseModel, ConfigDict, Field, ValidationError

from telco_twin.bootstrap.gcp_commands import (
    GcpContext,
    ProvisioningError,
    require_gcloud,
    run_gcloud,
)
from telco_twin.bootstrap.gcp_service_account import (
    ServiceAccountState,
    ensure_service_account,
)

POOL_ID: Literal["github-actions"] = "github-actions"
PROVIDER_ID: Literal["github-oidc"] = "github-oidc"
ISSUER = "https://token.actions.githubusercontent.com"
MAPPING = (
    "google.subject=assertion.sub,"
    "attribute.repository=assertion.repository,"
    "attribute.repository_owner_id=assertion.repository_owner_id"
)
REPOSITORIES = (
    "oyeong011/telco-counterfactual-twin",
    "oyeong011/mcp-evidence-plane",
)


class ProviderSnapshot(BaseModel):
    """Provider fields needed to restore an existing configuration."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)

    issuer: str = Field(validation_alias=AliasPath("oidc", "issuerUri"))
    mapping: dict[str, str] = Field(alias="attributeMapping")
    condition: str = Field(alias="attributeCondition")


@dataclass(frozen=True, slots=True)
class PersistentState:
    """WIF and service-account rollback state captured before mutation."""

    service_account_state: ServiceAccountState
    pool_created: bool
    provider_created: bool
    provider_snapshot: ProviderSnapshot | None

    @property
    def service_account(self) -> str:
        """Return the deploy service-account email."""
        return self.service_account_state.service_account


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    """Complete OIDC provider command configuration."""

    context: GcpContext
    provider_id: str
    issuer: str
    mapping: str
    condition: str


def provider_command(action: str, config: ProviderConfig) -> tuple[str, ...]:
    """Build an exact argv tuple for create/update OIDC provider operations."""
    return (
        "gcloud",
        "iam",
        "workload-identity-pools",
        "providers",
        action,
        config.provider_id,
        f"--project={config.context.project_id}",
        "--location=global",
        f"--workload-identity-pool={POOL_ID}",
        f"--issuer-uri={config.issuer}",
        f"--attribute-mapping={config.mapping}",
        f"--attribute-condition={config.condition}",
        "--quiet",
    )


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
    snapshot: ProviderSnapshot | None = None
    if not provider_created:
        try:
            snapshot = ProviderSnapshot.model_validate_json(provider_before.stdout)
        except ValidationError:
            code = "provider-snapshot-invalid"
            raise ProvisioningError(code) from None
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
    return PersistentState(
        service_account_state=service_account_state,
        pool_created=pool_created,
        provider_created=provider_created,
        provider_snapshot=snapshot,
    )
