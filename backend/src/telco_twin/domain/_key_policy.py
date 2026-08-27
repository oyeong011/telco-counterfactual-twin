"""Recursive semantic-key policy for every Twin contract boundary."""

from __future__ import annotations

import re
from functools import singledispatch
from typing import Final

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

KEY_POLICY_VERSION: Final = "1.0"
PII_KEY_TOKENS: Final = ("email", "gpsi", "imei", "imsi", "msisdn", "phone", "supi")
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
KEY_POLICY_ALLOW_EXAMPLES: Final = (
    "commandment_count",
    "config_history",
    "executioner_state",
    "shellfish_count",
    "tokenization_mode",
    "ue_cohort_id",
)
COLLAPSED_DIRECT_PII_STEMS: Final = PII_KEY_TOKENS
COLLAPSED_IDENTITY_SUBJECTS: Final = IDENTITY_SUBJECT_TOKENS
COLLAPSED_IDENTIFIER_STEMS: Final = IDENTIFIER_TOKENS
COLLAPSED_AUTHORITY_STEMS: Final = (
    "command",
    "execute",
    "execution",
    "revoke",
    "revocation",
    "shell",
)
COLLAPSED_ACTION_PREFIXES: Final = ("apply", "push")
COLLAPSED_ACTION_TARGETS: Final = ("config", "network", "payload")
COLLAPSED_ARBITRARY_URL_STEMS: Final = ("arbitrary", "url")
COLLAPSED_SECRET_STEMS: Final = ("credential", "passwd", "password", "secret", "token")
_CAMEL_ACRONYM_BOUNDARY: Final = re.compile(r"([A-Z]+)([A-Z][a-z])")
_CAMEL_WORD_BOUNDARY: Final = re.compile(r"([a-z0-9])([A-Z])")
_TOKEN_SEPARATOR: Final = re.compile(r"[^A-Za-z0-9]+")
_PII_TOKEN_SET: Final = frozenset(PII_KEY_TOKENS)
_IDENTITY_SUBJECT_SET: Final = frozenset(IDENTITY_SUBJECT_TOKENS)
_IDENTIFIER_SET: Final = frozenset(IDENTIFIER_TOKENS)
_AUTHORITY_TOKEN_SET: Final = frozenset(AUTHORITY_KEY_TOKENS)
_SECRET_TOKEN_SET: Final = frozenset(SECRET_KEY_TOKENS)
_PUSH_PAYLOAD: Final = frozenset(("push", "payload"))


def _key_tokens(value: str) -> frozenset[str]:
    acronym_expanded = _CAMEL_ACRONYM_BOUNDARY.sub(r"\1_\2", value)
    expanded = _CAMEL_WORD_BOUNDARY.sub(r"\1_\2", acronym_expanded)
    return frozenset(token.lower() for token in _TOKEN_SEPARATOR.split(expanded) if token)


def _collapsed_key(value: str) -> str:
    return "".join(character for character in value.lower() if character.isalnum())


def _contains_any(value: str, stems: tuple[str, ...]) -> bool:
    return any(stem in value for stem in stems)


def _contains_ordered_pair(
    value: str,
    prefixes: tuple[str, ...],
    suffixes: tuple[str, ...],
) -> bool:
    return any(
        prefix in value and _contains_any(value.partition(prefix)[2], suffixes)
        for prefix in prefixes
    )


def _validate_semantic_key(value: str) -> None:
    if value in KEY_POLICY_ALLOW_EXAMPLES:
        return
    tokens = _key_tokens(value)
    collapsed = _collapsed_key(value)
    if (
        tokens & _PII_TOKEN_SET
        or (tokens & _IDENTITY_SUBJECT_SET and tokens & _IDENTIFIER_SET)
        or _contains_any(collapsed, COLLAPSED_DIRECT_PII_STEMS)
        or _contains_ordered_pair(
            collapsed,
            COLLAPSED_IDENTITY_SUBJECTS,
            COLLAPSED_IDENTIFIER_STEMS,
        )
    ):
        fail_validation("pii_shaped_key", "PII-shaped keys are forbidden")
    if (
        tokens & _AUTHORITY_TOKEN_SET
        or tokens >= _PUSH_PAYLOAD
        or _contains_any(collapsed, COLLAPSED_AUTHORITY_STEMS)
        or _contains_ordered_pair(
            collapsed,
            COLLAPSED_ACTION_PREFIXES,
            COLLAPSED_ACTION_TARGETS,
        )
        or _contains_ordered_pair(
            collapsed,
            COLLAPSED_ARBITRARY_URL_STEMS[:1],
            COLLAPSED_ARBITRARY_URL_STEMS[1:],
        )
    ):
        fail_validation(
            "authority_shaped_key", "execution and command authority keys are forbidden"
        )
    if tokens & _SECRET_TOKEN_SET or _contains_any(collapsed, COLLAPSED_SECRET_STEMS):
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
