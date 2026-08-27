"""Shared scalar and boundary rules for Twin contracts."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Annotated, ClassVar, Final, Literal, LiteralString, Never

import rfc8785
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    WithJsonSchema,
)
from pydantic_core import PydanticCustomError

type JsonScalar = (
    str
    | Annotated[int, Field(ge=-(2**53) + 1, le=(2**53) - 1)]
    | Annotated[float, Field(ge=-(2**53) + 1, le=(2**53) - 1)]
    | bool
    | None
)
type PropertyMap = dict[str, JsonScalar]
type SchemaVersion = Literal["1.0"]

ID_PATTERN: Final = r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$"
BASE_KEY_PATTERN: Final = r"^[a-z][a-z0-9]*(?:[-_][a-z0-9]+)*$"
KEY_PATTERN: Final = (
    r"^(?!(?:email|gpsi|imei|imsi|msisdn|phone|subscriber[-_]?id|supi|"
    r"apply[-_]?to[-_]?network|command|execute|execution|push[-_]?config|"
    r"revoke|revocation|shell|url)$)[a-z][a-z0-9]*(?:[-_][a-z0-9]+)*$"
)
UTC_PATTERN: Final = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"
SHA256_PATTERN: Final = r"^[0-9a-f]{64}$"
GIT_SHA_PATTERN: Final = r"^[0-9a-f]{40}$"
SEMVER_PATTERN: Final = r"^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?$"
I_JSON_MAX_INTEGER: Final = (2**53) - 1
MAX_SAFE_KEY_LENGTH: Final = 64
_PII_KEYS: Final = frozenset(
    {"email", "gpsi", "imei", "imsi", "msisdn", "phone", "subscriberid", "supi"}
)
_AUTHORITY_KEYS: Final = frozenset(
    {
        "applytonetwork",
        "command",
        "execute",
        "execution",
        "pushconfig",
        "revoke",
        "revocation",
        "shell",
        "url",
    }
)


def _normalized_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def fail_validation(code: LiteralString, message: LiteralString) -> Never:
    """Raise one stable Pydantic boundary error."""
    raise PydanticCustomError(code, message)


def validate_safe_key(value: str) -> str:
    """Reject identity-shaped and authority-shaped dynamic keys."""
    if not 1 <= len(value) <= MAX_SAFE_KEY_LENGTH or re.fullmatch(BASE_KEY_PATTERN, value) is None:
        fail_validation("safe_key_format", "dynamic key format is invalid")
    normalized = _normalized_key(value)
    if normalized in _PII_KEYS:
        fail_validation("pii_shaped_key", "PII-shaped keys are forbidden")
    if normalized in _AUTHORITY_KEYS:
        fail_validation(
            "authority_shaped_key", "execution and command authority keys are forbidden"
        )
    return value


def _validate_property_map(value: PropertyMap) -> PropertyMap:
    """Apply safe-key rules to a bounded scalar property object."""
    for key in value:
        _ = validate_safe_key(key)
    for item in value.values():
        try:
            _ = rfc8785.dumps(item)
        except rfc8785.CanonicalizationError:
            fail_validation("i_json_domain", "property value is outside the I-JSON domain")
    return value


def validate_utc_timestamp(value: str) -> str:
    """Require a real UTC RFC3339 timestamp with whole-second precision."""
    if re.fullmatch(UTC_PATTERN, value) is None:
        fail_validation("utc_rfc3339_seconds", "timestamp must be UTC RFC3339 seconds")
    try:
        _ = datetime.fromisoformat(value)
    except ValueError:
        fail_validation("utc_rfc3339_seconds", "timestamp must be UTC RFC3339 seconds")
    return value


def utc_datetime(value: str) -> datetime:
    """Return the UTC-aware instant represented by a validated timestamp."""
    return datetime.fromisoformat(value).astimezone(UTC)


ContractId = Annotated[str, Field(min_length=3, max_length=96, pattern=ID_PATTERN)]
SafeKey = Annotated[
    str,
    AfterValidator(validate_safe_key),
    WithJsonSchema({"type": "string", "minLength": 1, "maxLength": 64, "pattern": KEY_PATTERN}),
]
UtcTimestamp = Annotated[
    str,
    AfterValidator(validate_utc_timestamp),
    WithJsonSchema({"type": "string", "pattern": UTC_PATTERN}),
]
Sha256Hex = Annotated[str, Field(pattern=SHA256_PATTERN)]
GitCommitSha = Annotated[str, Field(pattern=GIT_SHA_PATTERN)]
SemanticVersion = Annotated[str, Field(pattern=SEMVER_PATTERN)]
Seed = Annotated[int, Field(ge=0, le=I_JSON_MAX_INTEGER)]
SafeProperties = Annotated[
    dict[SafeKey, JsonScalar], Field(max_length=32), AfterValidator(_validate_property_map)
]


class StrictContract(BaseModel):
    """Frozen, closed Pydantic boundary shared by every contract."""

    model_config: ClassVar[ConfigDict] = ConfigDict(
        allow_inf_nan=False,
        extra="forbid",
        frozen=True,
        validate_default=True,
    )


class VersionedExtensions(StrictContract):
    """The sole versioned escape hatch for forward-compatible scalar metadata."""

    schema_version: SchemaVersion
    values: SafeProperties = Field(default_factory=dict)


EMPTY_EXTENSIONS: Final = VersionedExtensions(schema_version="1.0")


class RootContract(StrictContract):
    """Versioned root object with the only permitted extension envelope."""

    schema_version: SchemaVersion
    extensions: VersionedExtensions | None = None
