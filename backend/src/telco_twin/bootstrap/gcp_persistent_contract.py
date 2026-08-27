"""Typed persistent WIF state shared by setup and rollback."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Literal

from pydantic import AliasPath, BaseModel, ConfigDict, Field

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
