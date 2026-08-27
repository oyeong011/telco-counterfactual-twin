"""Shared scalar and boundary rules for Twin contracts."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from functools import singledispatch
from typing import Annotated, ClassVar, Final, Literal, LiteralString, Never

import rfc8785
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    WithJsonSchema,
    model_validator,
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
type ContractInput = (
    JsonScalar
    | BaseModel
    | list["ContractInput"]
    | tuple["ContractInput", ...]
    | dict[str, "ContractInput"]
)

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
KEY_POLICY_VERSION: Final = "1.0"
PII_KEY_TOKENS: Final = (
    "email",
    "gpsi",
    "imei",
    "imsi",
    "msisdn",
    "phone",
    "supi",
)
IDENTITY_SUBJECT_TOKENS: Final = ("customer", "subscriber")
IDENTIFIER_TOKENS: Final = ("id", "identifier", "identifiers", "identity")
AUTHORITY_KEY_TOKENS: Final = (
    "command",
    "execute",
    "execution",
    "revoke",
    "revocation",
    "shell",
    "uri",
    "url",
)
SECRET_KEY_TOKENS: Final = (
    "credential",
    "credentials",
    "passwd",
    "password",
    "passwords",
    "secret",
    "secrets",
    "token",
    "tokens",
)
FORBIDDEN_KEY_COMBINATIONS: Final = (
    ("customer", "id"),
    ("customer", "identifier"),
    ("subscriber", "id"),
    ("subscriber", "identifier"),
    ("push", "payload"),
)
KEY_POLICY_ALLOW_EXAMPLES: Final = ("config_history", "ue_cohort_id")
COLLAPSED_PII_KEYS: Final = (
    "customerid",
    "emailaddress",
    "subscriberid",
)
COLLAPSED_AUTHORITY_KEYS: Final = (
    "applytonetwork",
    "pushpayload",
    "shellcommand",
)
COLLAPSED_SECRET_KEYS: Final = ("accesstoken",)
_CAMEL_ACRONYM_BOUNDARY: Final = re.compile(r"([A-Z]+)([A-Z][a-z])")
_CAMEL_WORD_BOUNDARY: Final = re.compile(r"([a-z0-9])([A-Z])")
_TOKEN_SEPARATOR: Final = re.compile(r"[^A-Za-z0-9]+")
_PII_TOKEN_SET: Final = frozenset(PII_KEY_TOKENS)
_IDENTITY_SUBJECT_SET: Final = frozenset(IDENTITY_SUBJECT_TOKENS)
_IDENTIFIER_SET: Final = frozenset(IDENTIFIER_TOKENS)
_AUTHORITY_TOKEN_SET: Final = frozenset(AUTHORITY_KEY_TOKENS)
_SECRET_TOKEN_SET: Final = frozenset(SECRET_KEY_TOKENS)
_PUSH_PAYLOAD: Final = frozenset(("push", "payload"))
_COLLAPSED_PII_SET: Final = frozenset(COLLAPSED_PII_KEYS)
_COLLAPSED_AUTHORITY_SET: Final = frozenset(COLLAPSED_AUTHORITY_KEYS)
_COLLAPSED_SECRET_SET: Final = frozenset(COLLAPSED_SECRET_KEYS)


def _key_tokens(value: str) -> tuple[str, ...]:
    acronym_expanded = _CAMEL_ACRONYM_BOUNDARY.sub(r"\1_\2", value)
    expanded = _CAMEL_WORD_BOUNDARY.sub(r"\1_\2", acronym_expanded)
    return tuple(token.lower() for token in _TOKEN_SEPARATOR.split(expanded) if token)


def _collapsed_key(value: str) -> str:
    return "".join(character for character in value.lower() if character.isalnum())


def _validate_semantic_key(value: str) -> None:
    tokens = frozenset(_key_tokens(value))
    collapsed = _collapsed_key(value)
    has_identity_subject = bool(tokens & _IDENTITY_SUBJECT_SET)
    has_identifier = bool(tokens & _IDENTIFIER_SET)
    if (
        tokens & _PII_TOKEN_SET
        or (has_identity_subject and has_identifier)
        or collapsed in _COLLAPSED_PII_SET
    ):
        fail_validation("pii_shaped_key", "PII-shaped keys are forbidden")
    if (
        tokens & _AUTHORITY_TOKEN_SET
        or tokens >= _PUSH_PAYLOAD
        or collapsed in _COLLAPSED_AUTHORITY_SET
    ):
        fail_validation(
            "authority_shaped_key", "execution and command authority keys are forbidden"
        )
    if tokens & _SECRET_TOKEN_SET or collapsed in _COLLAPSED_SECRET_SET:
        fail_validation("secret_shaped_key", "secret-shaped keys are forbidden")


@singledispatch
def _validate_contract_keys(_value: ContractInput) -> None:
    """Accept scalar and already-parsed model leaves."""


def _validate_mapping_keys(value: dict[str, ContractInput]) -> None:
    for key, nested in value.items():
        _validate_semantic_key(key)
        _validate_contract_keys(nested)


def _validate_list_keys(value: list[ContractInput]) -> None:
    for item in value:
        _validate_contract_keys(item)


def _validate_tuple_keys(value: tuple[ContractInput, ...]) -> None:
    for item in value:
        _validate_contract_keys(item)


_ = _validate_contract_keys.register(dict, _validate_mapping_keys)
_ = _validate_contract_keys.register(list, _validate_list_keys)
_ = _validate_contract_keys.register(tuple, _validate_tuple_keys)


def fail_validation(code: LiteralString, message: LiteralString) -> Never:
    """Raise one stable Pydantic boundary error."""
    raise PydanticCustomError(code, message)


def validate_safe_key(value: str) -> str:
    """Reject identity-shaped and authority-shaped dynamic keys."""
    _validate_semantic_key(value)
    if not 1 <= len(value) <= MAX_SAFE_KEY_LENGTH or re.fullmatch(BASE_KEY_PATTERN, value) is None:
        fail_validation("safe_key_format", "dynamic key format is invalid")
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

    @model_validator(mode="before")
    @classmethod
    def semantic_keys_are_safe(cls, value: ContractInput) -> ContractInput:
        """Reject semantic PII, authority, and secret keys at any nesting depth."""
        _validate_contract_keys(value)
        return value


class VersionedExtensions(StrictContract):
    """The sole versioned escape hatch for forward-compatible scalar metadata."""

    schema_version: SchemaVersion
    values: SafeProperties = Field(default_factory=dict)


EMPTY_EXTENSIONS: Final = VersionedExtensions(schema_version="1.0")


class RootContract(StrictContract):
    """Versioned root object with the only permitted extension envelope."""

    schema_version: SchemaVersion
    extensions: VersionedExtensions | None = None
