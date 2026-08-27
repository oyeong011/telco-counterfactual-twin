from __future__ import annotations

from enum import StrEnum, unique
from itertools import permutations
from typing import Final, assert_never

import pytest
from pydantic import BaseModel, ValidationError

from telco_twin.domain._key_policy import validate_semantic_key
from telco_twin.domain.scenario import Scenario
from telco_twin.domain.topology import Topology

from .contract_payloads import JsonObject, topology_payload, valid_domain_cases

type SemanticGroupCase = tuple[tuple[str, str], str]

PII_GROUP_CASES: Final[tuple[SemanticGroupCase, ...]] = tuple(
    ((subject, identifier), "pii_shaped_key")
    for subject in ("customer", "subscriber")
    for identifier in ("id", "identifier", "identifiers", "identity")
)
AUTHORITY_GROUP_CASES: Final[tuple[SemanticGroupCase, ...]] = (
    tuple((("push", target), "authority_shaped_key") for target in ("config", "network", "payload"))
    + tuple(
        (("apply", target), "authority_shaped_key") for target in ("config", "network", "payload")
    )
    + ((("shell", "command"), "authority_shaped_key"),)
    + tuple(
        ((verb, action), "authority_shaped_key")
        for verb in ("execute", "execution")
        for action in ("action", "command", "network", "operation", "payload", "plan", "request")
    )
    + tuple(
        ((verb, detail), "authority_shaped_key")
        for verb in ("revoke", "revocation")
        for detail in ("id", "identifier", "reason", "status", "token")
    )
)
SECRET_GROUP_CASES: Final[tuple[SemanticGroupCase, ...]] = tuple(
    ((subject, secret), "secret_shaped_key")
    for subject in ("access", "api")
    for secret in ("key", "secret", "token")
)
FORBIDDEN_GROUP_CASES: Final = PII_GROUP_CASES + AUTHORITY_GROUP_CASES + SECRET_GROUP_CASES
DIRECT_SENSITIVE_CASES: Final[tuple[SemanticGroupCase, ...]] = (
    (("email", "digest"), "pii_shaped_key"),
    (("phone", "number"), "pii_shaped_key"),
    (("imsi", "hash"), "pii_shaped_key"),
    (("msisdn", "value"), "pii_shaped_key"),
    (("credential", "fingerprint"), "secret_shaped_key"),
    (("password", "hash"), "secret_shaped_key"),
    (("secret", "value"), "secret_shaped_key"),
    (("token", "value"), "secret_shaped_key"),
)
EXACT_AUTHORITY_KEYS: Final = (
    "command",
    "execute",
    "execution",
    "revoke",
    "revocation",
    "shell",
)
URL_EDGE_TOKEN_CASES: Final = (
    ("url", "fetch"),
    ("callback", "url"),
    ("uri", "fetch"),
    ("redirect", "uri"),
    ("url", "loader"),
    ("webhook", "uri"),
)
SAFE_EXACT_TOKEN_CASES: Final = (
    ("commandment", "count"),
    ("config", "history"),
    ("executioner", "state"),
    ("shellfish", "count"),
    ("tokenization", "mode"),
    ("ue", "cohort", "id"),
)
SAFE_NATURAL_TOKEN_CASES: Final = (("security", "level"), ("duration", "ms"))


@unique
class Boundary(StrEnum):
    ROOT = "root"
    EXTENSIONS = "extensions"
    NESTED = "nested"


def _key_forms(tokens: tuple[str, ...]) -> tuple[str, ...]:
    camel = tokens[0] + "".join(token.title() for token in tokens[1:])
    forms = (
        "_".join(tokens),
        "-".join(tokens),
        camel,
        "".join(tokens),
        "_".join(tokens).upper(),
    )
    return tuple(dict.fromkeys(forms))


def _boundary_key_forms(tokens: tuple[str, ...]) -> tuple[str, ...]:
    return ("_".join(tokens), "-".join(tokens), "".join(tokens))


def _validate_at_boundary(key: str, boundary: Boundary) -> None:
    model: type[BaseModel]
    payload: JsonObject
    match boundary:
        case Boundary.ROOT:
            model = Scenario
            _, payload = next(case for case in valid_domain_cases() if case[0] is Scenario)
            payload[key] = "synthetic"
        case Boundary.EXTENSIONS:
            model = Scenario
            _, payload = next(case for case in valid_domain_cases() if case[0] is Scenario)
            payload["extensions"] = {
                "schema_version": "1.0",
                "values": {key: "synthetic"},
            }
        case Boundary.NESTED:
            model = Topology
            payload = topology_payload()
            nodes = payload["nodes"]
            assert isinstance(nodes, list)
            first = nodes[0]
            assert isinstance(first, dict)
            first["attributes"] = {key: "synthetic"}
        case _:
            assert_never(boundary)
    _ = model.model_validate(payload)


@pytest.mark.parametrize(("tokens", "expected_code"), FORBIDDEN_GROUP_CASES)
def test_forbidden_group_outcome_survives_key_transformations(
    tokens: tuple[str, str],
    expected_code: str,
) -> None:
    for ordering in permutations(tokens):
        for key in _key_forms(ordering):
            for boundary in Boundary:
                with pytest.raises(ValidationError) as caught:
                    _validate_at_boundary(key, boundary)
                assert expected_code in {item["type"] for item in caught.value.errors()}, (
                    f"{key}@{boundary.value}"
                )


@pytest.mark.parametrize(("tokens", "expected_code"), DIRECT_SENSITIVE_CASES)
def test_direct_sensitive_lexeme_survives_key_transformations(
    tokens: tuple[str, str],
    expected_code: str,
) -> None:
    for ordering in permutations(tokens):
        for key in _key_forms(ordering):
            for boundary in Boundary:
                with pytest.raises(ValidationError) as caught:
                    _validate_at_boundary(key, boundary)
                assert expected_code in {item["type"] for item in caught.value.errors()}, (
                    f"{key}@{boundary.value}"
                )


@pytest.mark.parametrize("key", EXACT_AUTHORITY_KEYS)
def test_exact_authority_key_is_case_invariant(key: str) -> None:
    for variant in (key, key.title(), key.upper()):
        for boundary in Boundary:
            with pytest.raises(ValidationError) as caught:
                _validate_at_boundary(variant, boundary)
            assert "authority_shaped_key" in {item["type"] for item in caught.value.errors()}, (
                f"{variant}@{boundary.value}"
            )


@pytest.mark.parametrize("tokens", URL_EDGE_TOKEN_CASES)
def test_url_and_uri_at_semantic_edges_are_always_authority(
    tokens: tuple[str, str],
) -> None:
    for key in _key_forms(tokens):
        for boundary in Boundary:
            with pytest.raises(ValidationError) as caught:
                _validate_at_boundary(key, boundary)
            assert "authority_shaped_key" in {item["type"] for item in caught.value.errors()}, (
                f"{key}@{boundary.value}"
            )


@pytest.mark.parametrize(
    "tokens",
    SAFE_EXACT_TOKEN_CASES + SAFE_NATURAL_TOKEN_CASES,
)
def test_safe_words_do_not_trigger_semantic_policy_after_transformations(
    tokens: tuple[str, ...],
) -> None:
    for key in _key_forms(tokens):
        validate_semantic_key(key)


@pytest.mark.parametrize(
    "tokens",
    SAFE_EXACT_TOKEN_CASES + SAFE_NATURAL_TOKEN_CASES,
)
def test_safe_words_remain_valid_at_dynamic_boundaries(
    tokens: tuple[str, ...],
) -> None:
    for key in _boundary_key_forms(tokens):
        _validate_at_boundary(key, Boundary.EXTENSIONS)
        _validate_at_boundary(key, Boundary.NESTED)


@pytest.mark.parametrize("tokens", SAFE_EXACT_TOKEN_CASES)
def test_unsafe_prefix_or_suffix_invalidates_safe_exact_key(
    tokens: tuple[str, ...],
) -> None:
    safe_key = "_".join(tokens)
    cases = (
        (f"access_token_{safe_key}", "secret_shaped_key"),
        (f"{safe_key}_shell_command", "authority_shaped_key"),
    )
    for key, expected_code in cases:
        for boundary in (Boundary.EXTENSIONS, Boundary.NESTED):
            with pytest.raises(ValidationError) as caught:
                _validate_at_boundary(key, boundary)
            assert expected_code in {item["type"] for item in caught.value.errors()}, (
                f"{key}@{boundary.value}"
            )
