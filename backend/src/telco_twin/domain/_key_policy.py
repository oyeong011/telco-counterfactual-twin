"""Recursive semantic-key policy for every Twin contract boundary."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import singledispatch
from typing import Final, Literal

from pydantic import BaseModel

from telco_twin.domain._validation import fail_validation

type KeyPolicyInput = (
    str
    | int
    | float
    | bool
    | BaseModel
    | list["KeyPolicyInput"]
    | tuple["KeyPolicyInput", ...]
    | dict[str, "KeyPolicyInput"]
    | None
)
type LexemeFamily = tuple[str, ...]
type LexemeGroup = tuple[LexemeFamily, LexemeFamily]


@dataclass(frozen=True, slots=True)
class KeyPolicySpec:
    """Immutable source shared by runtime matching and schema metadata."""

    version: str
    normalization: Literal["lowercase_alphanumeric"]
    safe_exact_keys: tuple[str, ...]
    pii_direct_stems: tuple[str, ...]
    authority_direct_stems: tuple[str, ...]
    secret_direct_stems: tuple[str, ...]
    authority_url_uri_stems: tuple[str, ...]
    api_group_stems: tuple[str, ...]
    api_group_targets: tuple[str, ...]
    api_benign_embedded_lexemes: tuple[str, ...]
    pii_unordered_groups: tuple[LexemeGroup, ...]
    authority_unordered_groups: tuple[LexemeGroup, ...]
    secret_unordered_groups: tuple[LexemeGroup, ...]


KEY_POLICY: Final = KeyPolicySpec(
    version="1.0",
    normalization="lowercase_alphanumeric",
    safe_exact_keys=(
        "commandment_count",
        "config_history",
        "curiosity_score",
        "duration_ms",
        "executioner_state",
        "flourish_count",
        "jurisdiction_code",
        "maturity_score",
        "purity_index",
        "security_level",
        "shellfish_count",
        "tokenization_mode",
        "ue_cohort_id",
    ),
    pii_direct_stems=(
        "customer",
        "email",
        "gpsi",
        "imei",
        "imsi",
        "msisdn",
        "phone",
        "subscriber",
        "supi",
    ),
    authority_direct_stems=(
        "command",
        "execute",
        "execution",
        "revoke",
        "revocation",
        "shell",
    ),
    secret_direct_stems=("credential", "passwd", "password", "secret", "token"),
    authority_url_uri_stems=("uri", "url"),
    api_group_stems=("api",),
    api_group_targets=("key", "secret", "token"),
    api_benign_embedded_lexemes=("rapid",),
    pii_unordered_groups=(
        (("customer", "subscriber"), ("id", "identifier", "identifiers", "identity")),
    ),
    authority_unordered_groups=(
        (("push",), ("config", "network", "payload")),
        (("apply",), ("config", "network", "payload")),
        (("shell",), ("command",)),
        (("arbitrary",), ("uri", "url")),
        (
            ("execute", "execution"),
            ("action", "command", "network", "operation", "payload", "plan", "request"),
        ),
        (("command",), ("action", "network", "operation", "payload", "plan", "request")),
        (("revoke", "revocation"), ("id", "identifier", "reason", "status", "token")),
    ),
    secret_unordered_groups=((("access",), ("key", "secret", "token")),),
)
_CAMEL_ACRONYM_BOUNDARY: Final = re.compile(r"([A-Z]+)([A-Z][a-z])")
_CAMEL_WORD_BOUNDARY: Final = re.compile(r"([a-z0-9])([A-Z])")
_TOKEN_SEPARATOR: Final = re.compile(r"[^A-Za-z0-9]+")


def _key_tokens(value: str) -> frozenset[str]:
    acronym_expanded = _CAMEL_ACRONYM_BOUNDARY.sub(r"\1_\2", value)
    expanded = _CAMEL_WORD_BOUNDARY.sub(r"\1_\2", acronym_expanded)
    return frozenset(token.lower() for token in _TOKEN_SEPARATOR.split(expanded) if token)


def _normalized_key(value: str) -> str:
    return "".join(character for character in value.lower() if character.isalnum())


_NORMALIZED_SAFE_KEYS: Final = frozenset(_normalized_key(key) for key in KEY_POLICY.safe_exact_keys)


def _contains_any(value: str, stems: tuple[str, ...]) -> bool:
    return any(stem in value for stem in stems)


def _tokens_match_group(tokens: frozenset[str], group: LexemeGroup) -> bool:
    return all(any(lexeme in tokens for lexeme in family) for family in group)


def _collapsed_contains_lexeme(value: str, lexeme: str) -> bool:
    return lexeme in value


def _collapsed_matches_group(value: str, group: LexemeGroup) -> bool:
    left, right = group
    families_present = all(
        any(_collapsed_contains_lexeme(value, lexeme) for lexeme in family) for family in group
    )
    adjacent_pair = any(
        first + second in value or second + first in value for first in left for second in right
    )
    return families_present or adjacent_pair


def _matches_groups(
    tokens: frozenset[str],
    normalized: str,
    groups: tuple[LexemeGroup, ...],
) -> bool:
    return any(
        _tokens_match_group(tokens, group) or _collapsed_matches_group(normalized, group)
        for group in groups
    )


def _matches_api_group(tokens: frozenset[str], normalized: str) -> bool:
    parsed_match = any(stem in tokens for stem in KEY_POLICY.api_group_stems) and any(
        target in tokens for target in KEY_POLICY.api_group_targets
    )
    shielded = normalized
    for benign in KEY_POLICY.api_benign_embedded_lexemes:
        shielded = shielded.replace(benign, "")
    collapsed_match = _contains_any(shielded, KEY_POLICY.api_group_stems) and _contains_any(
        shielded, KEY_POLICY.api_group_targets
    )
    return parsed_match or collapsed_match


def _validate_semantic_key(value: str) -> None:
    normalized = _normalized_key(value)
    if normalized in _NORMALIZED_SAFE_KEYS:
        return
    tokens = _key_tokens(value)
    if _contains_any(normalized, KEY_POLICY.pii_direct_stems) or _matches_groups(
        tokens, normalized, KEY_POLICY.pii_unordered_groups
    ):
        fail_validation("pii_shaped_key", "PII-shaped keys are forbidden")
    if (
        _contains_any(normalized, KEY_POLICY.authority_direct_stems)
        or _contains_any(normalized, KEY_POLICY.authority_url_uri_stems)
        or _matches_groups(tokens, normalized, KEY_POLICY.authority_unordered_groups)
    ):
        fail_validation(
            "authority_shaped_key", "execution and command authority keys are forbidden"
        )
    if (
        _contains_any(normalized, KEY_POLICY.secret_direct_stems)
        or _matches_groups(tokens, normalized, KEY_POLICY.secret_unordered_groups)
        or _matches_api_group(tokens, normalized)
    ):
        fail_validation("secret_shaped_key", "secret-shaped keys are forbidden")


@singledispatch
def validate_contract_keys(_value: KeyPolicyInput) -> None:
    """Accept scalar and already-parsed model leaves."""


def _validate_mapping_keys(value: dict[str, KeyPolicyInput]) -> None:
    for key, nested in value.items():
        _validate_semantic_key(key)
        validate_contract_keys(nested)


def _validate_sequence_keys(value: list[KeyPolicyInput]) -> None:
    for item in value:
        validate_contract_keys(item)


def _validate_tuple_keys(value: tuple[KeyPolicyInput, ...]) -> None:
    for item in value:
        validate_contract_keys(item)


_ = validate_contract_keys.register(dict, _validate_mapping_keys)
_ = validate_contract_keys.register(list, _validate_sequence_keys)
_ = validate_contract_keys.register(tuple, _validate_tuple_keys)


def validate_semantic_key(value: str) -> None:
    """Reject identity-shaped, authority-shaped, and secret-shaped keys."""
    _validate_semantic_key(value)
