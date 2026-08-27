"""Typed persistent WIF state shared by setup and rollback."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Literal

from pydantic import AliasPath, BaseModel, ConfigDict, Field

from telco_twin.bootstrap.gcp_reconciliation import (
    DEFAULT_RECONCILIATION_POLICY,
    ReconciliationPolicy,
)

if TYPE_CHECKING:
    from telco_twin.bootstrap.gcp_commands import GcpContext
    from telco_twin.bootstrap.gcp_service_account import ServiceAccountState

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

    def matches(self, config: ProviderConfig) -> bool:
        """Compare the provider snapshot with one exact write configuration."""
        expected_mapping: dict[str, str] = {}
        for item in config.mapping.split(","):
            key, value = item.split("=", 1)
            expected_mapping[key] = value
        return (
            self.issuer == config.issuer
            and self.mapping == expected_mapping
            and self.condition == config.condition
        )


class PoolSnapshot(BaseModel):
    """Persistent pool identity used to guard created-resource deletion."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)
    name: str
    display_name: str = Field(alias="displayName")


@dataclass(frozen=True, slots=True)
class PoolRollbackIntent:
    """Exact pool deletion ownership registered before create dispatch."""

    context: GcpContext
    policy: ReconciliationPolicy = DEFAULT_RECONCILIATION_POLICY

    @property
    def resource_name(self) -> str:
        """Return the exact pool resource identity."""
        return (
            f"projects/{self.context.project_number}/locations/global/"
            f"workloadIdentityPools/{POOL_ID}"
        )

    def matches(self, snapshot: PoolSnapshot) -> bool:
        """Require the exact resource and preflight display fingerprint."""
        return snapshot.name == self.resource_name and snapshot.display_name == "GitHub Actions"


@dataclass(frozen=True, slots=True)
class PersistentState:
    """WIF and service-account rollback state captured before mutation."""

    service_account_state: ServiceAccountState
    pool_intent: PoolRollbackIntent | None
    provider_create_intent: ProviderConfig | None
    provider_target: ProviderConfig | None
    provider_snapshot: ProviderSnapshot | None
    policy: ReconciliationPolicy = DEFAULT_RECONCILIATION_POLICY

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
