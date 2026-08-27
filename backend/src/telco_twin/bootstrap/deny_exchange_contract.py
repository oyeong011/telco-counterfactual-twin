"""Typed Google STS denial-classification contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Final, Literal

from pydantic import AliasPath, BaseModel, ConfigDict, Field

type DenyClassificationStatus = Literal[
    "deny-rejected",
    "deny-exchange-rejection-unproven",
    "deny-exchange-unexpected-success",
]

EXPECTED_ISSUER: Final = "https://token.actions.githubusercontent.com"
EXPECTED_CONDITION: Final = "assertion.repository=='oyeong011/nonmatching-preflight'"
EXPECTED_MAPPING_ITEMS: Final = (
    ("attribute.repository", "assertion.repository"),
    ("attribute.repository_owner_id", "assertion.repository_owner_id"),
    ("google.subject", "assertion.sub"),
)
CONDITION_REJECTION_DESCRIPTION: Final = (
    "The given credential is rejected by the attribute condition."
)
HTTP_BAD_REQUEST: Final = 400
HTTP_SUCCESS_MIN: Final = 200
HTTP_SUCCESS_MAX: Final = 300


class DenyProviderSnapshot(BaseModel):
    """Gcloud provider projection required before token exchange."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)

    name: str = Field(min_length=1)
    issuer: str = Field(validation_alias=AliasPath("oidc", "issuerUri"))
    mapping: dict[str, str] = Field(alias="attributeMapping")
    condition: str = Field(alias="attributeCondition")


class StsErrorResponse(BaseModel):
    """OAuth error projection returned by Google STS."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)

    error: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    error_description: str = Field(min_length=1)


class StsSuccessResponse(BaseModel):
    """Successful STS projection used only to detect an unexpected token."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)

    access_token: str = Field(min_length=1)


class DenyExchangeClassification(BaseModel):
    """Redacted classifier result consumed by the workflow assertion."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    status: DenyClassificationStatus
    provider_verified: bool
    http_status: int | None
    sts_error: str | None
    provider_evidence: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    exchange_evidence: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class ClassificationFacts:
    """Internal facts projected into a redacted report."""

    status: DenyClassificationStatus
    provider_verified: bool
    http_status: int | None
    sts_error: str | None
    seed: str
