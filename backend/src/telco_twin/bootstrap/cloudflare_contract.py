"""Typed Cloudflare API response contracts for the Pages authority probe."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from telco_twin.bootstrap.probe_errors import ProviderProbeError

if TYPE_CHECKING:
    import httpx2

HTTP_SUCCESS_MIN = 200
HTTP_SUCCESS_MAX = 300


class TokenResult(BaseModel):
    """Verified Cloudflare token projection."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)
    id: str = Field(min_length=1)
    status: Literal["active"]


class TokenEnvelope(BaseModel):
    """Token verification envelope."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)
    success: Literal[True]
    result: TokenResult


class AccountResult(BaseModel):
    """Cloudflare account projection."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)
    id: str = Field(min_length=1)


class AccountEnvelope(BaseModel):
    """Account GET envelope."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)
    success: Literal[True]
    result: AccountResult


class ProjectResult(BaseModel):
    """Cloudflare Pages project projection."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)


class ProjectEnvelope(BaseModel):
    """Pages project create envelope."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)
    success: Literal[True]
    result: ProjectResult


class ProjectsEnvelope(BaseModel):
    """Pages project list envelope."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)
    success: Literal[True]
    result: tuple[ProjectResult, ...]


class DeploymentResult(BaseModel):
    """Cloudflare Pages deployment projection."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)
    id: str = Field(min_length=1)


class DeploymentsEnvelope(BaseModel):
    """Pages deployment list envelope."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)
    success: Literal[True]
    result: tuple[DeploymentResult, ...]


class OperationEnvelope(BaseModel):
    """Cloudflare mutation response success projection."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)
    success: Literal[True]


def parse_response[T: BaseModel](
    response: httpx2.Response,
    model: type[T],
    operation: str,
) -> T:
    """Parse a successful Cloudflare response or raise a stable redacted code."""
    if response.status_code < HTTP_SUCCESS_MIN or response.status_code >= HTTP_SUCCESS_MAX:
        code = f"cloudflare-{operation}-http-{response.status_code}"
        raise ProviderProbeError(code)
    try:
        return model.model_validate_json(response.content)
    except ValidationError:
        code = f"cloudflare-{operation}-invalid-json"
        raise ProviderProbeError(code) from None
