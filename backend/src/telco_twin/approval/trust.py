"""Immutable approval trust configuration and production trust parsing."""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum, unique
from typing import ClassVar, Final, Self

from pydantic import ConfigDict, RootModel, ValidationError, model_validator

from telco_twin.domain._contract import Sha256Hex
from telco_twin.domain._validation import fail_validation
from telco_twin.domain.approval import (
    Environment,
    RootDescriptor,
    validate_root_trust,
)

TRUSTED_ROOTS_ENV: Final = "APPROVAL_TRUSTED_ROOT_HASHES_JSON"


@dataclass(frozen=True, slots=True)
class ApprovalTrustConfig:
    """Application-owned root/environment facts used by the evidence ledger."""

    environment: Environment
    root: RootDescriptor
    trusted_root_hashes: frozenset[Sha256Hex]

    def __post_init__(self) -> None:
        """Reject configuration whose descriptor is not independently trusted."""
        validate_root_trust(self.root, self.environment, self.trusted_root_hashes)


class _TrustedRootHashes(RootModel[frozenset[Sha256Hex]]):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    @model_validator(mode="after")
    def is_nonempty(self) -> Self:
        if not self.root:
            fail_validation("trusted_roots_empty", "trusted root set cannot be empty")
        return self


@unique
class TrustedRootConfigCode(StrEnum):
    """Stable production trusted-root configuration failures."""

    MISSING = "trusted-roots-missing"
    INVALID = "trusted-roots-invalid"


@dataclass(frozen=True, slots=True)
class TrustedRootConfigRejected:
    """Fail-closed environment parsing result."""

    code: TrustedRootConfigCode


type TrustedRootConfigResult = frozenset[Sha256Hex] | TrustedRootConfigRejected


def load_production_trusted_roots() -> TrustedRootConfigResult:
    """Parse an independently configured nonempty JSON hash set."""
    encoded = os.getenv(TRUSTED_ROOTS_ENV)
    if encoded is None:
        return TrustedRootConfigRejected(TrustedRootConfigCode.MISSING)
    try:
        parsed = _TrustedRootHashes.model_validate_json(encoded)
    except ValidationError:
        return TrustedRootConfigRejected(TrustedRootConfigCode.INVALID)
    return parsed.root
