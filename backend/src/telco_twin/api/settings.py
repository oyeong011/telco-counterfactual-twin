"""Closed environment configuration for the Twin API boundary."""
# ruff: noqa: TC001 - Pydantic resolves branded field types at runtime.

from __future__ import annotations

from typing import ClassVar, Final, Self

from pydantic import ConfigDict, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from telco_twin.approval.authority_contracts import AuthorityMode
from telco_twin.domain._contract import GitCommitSha, UtcTimestamp
from telco_twin.domain._validation import fail_validation

LOCAL_DEMO_MATERIAL: Final = "local-test-demo-material-32-bytes"
ZERO_GIT_SHA: Final = "0" * 40
IMAGE_PATTERN: Final = r"^sha256:[0-9a-f]{64}$"


class ApiSettings(BaseSettings):
    """Parse deployment inputs once without representing private root material."""

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_prefix="TWIN_",
        extra="ignore",
        frozen=True,
    )

    environment: AuthorityMode = AuthorityMode.LOCAL
    allowed_origins: tuple[str, ...] = (
        "http://localhost:4173",
        "http://localhost:5173",
        "http://testserver",
    )
    demo_token_signing_secret: SecretStr = SecretStr(LOCAL_DEMO_MATERIAL)
    approval_root_descriptor_json: str | None = None
    jwt_issuer: str | None = None
    jwt_audience: str | None = None
    jwt_jwks_json: str | None = None
    runtime_source_commit_sha: GitCommitSha = ZERO_GIT_SHA
    release_commit_sha: GitCommitSha = ZERO_GIT_SHA
    built_at: UtcTimestamp = "2026-08-27T00:00:00Z"
    deployed_image_digest: str | None = Field(default=None, pattern=IMAGE_PATTERN)
    expected_image_digest: str | None = Field(default=None, pattern=IMAGE_PATTERN)

    @model_validator(mode="after")
    def configuration_is_closed_and_fail_safe(self) -> Self:
        """Reject partial JWT and unsafe production identity configuration."""
        jwt_values = (self.jwt_issuer, self.jwt_audience, self.jwt_jwks_json)
        if any(value is not None for value in jwt_values) and not all(
            value is not None for value in jwt_values
        ):
            fail_validation("jwt_config_incomplete", "issuer, audience, and JWKS must be complete")
        if self.environment is AuthorityMode.PRODUCTION:
            secret = self.demo_token_signing_secret.get_secret_value().lower()
            if secret == LOCAL_DEMO_MATERIAL or "test" in secret:
                fail_validation("production_demo_secret", "production demo secret is test-only")
            if self.approval_root_descriptor_json is None:
                fail_validation("production_root_missing", "production root descriptor is required")
            if (
                self.deployed_image_digest is None
                or self.expected_image_digest is None
                or self.deployed_image_digest != self.expected_image_digest
            ):
                fail_validation("production_digest_mismatch", "production digest must be verified")
        return self

    @property
    def jwt_is_configured(self) -> bool:
        """Return true only for the all-or-none JWT configuration."""
        return self.jwt_issuer is not None


class ApiModelConfig:
    """Shared frozen/closed Pydantic configuration for API-only models."""

    value: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)
