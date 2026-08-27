from __future__ import annotations

from enum import StrEnum, unique
from typing import Final, assert_never

import pytest
from pydantic import BaseModel, ValidationError

from telco_twin.domain._key_policy import validate_semantic_key
from telco_twin.domain.scenario import Scenario
from telco_twin.domain.topology import Topology

from .contract_payloads import JsonObject, topology_payload, valid_domain_cases

type StemCase = tuple[str, str]
type CompositeCase = tuple[tuple[str, ...], str]

DANGEROUS_STEM_CASES: Final[tuple[StemCase, ...]] = (
    tuple((stem, "pii_shaped_key") for stem in ("customer", "subscriber"))
    + tuple(
        (stem, "pii_shaped_key")
        for stem in ("email", "gpsi", "imei", "imsi", "msisdn", "phone", "supi")
    )
    + tuple(
        (stem, "authority_shaped_key")
        for stem in ("shell", "command", "execute", "execution", "revoke", "revocation")
    )
    + tuple(
        (stem, "secret_shaped_key")
        for stem in ("credential", "passwd", "password", "secret", "token")
    )
)
REVIEWER_CASES: Final[tuple[StemCase, ...]] = (
    ("shell_request", "authority_shaped_key"),
    ("execute_job", "authority_shaped_key"),
    ("execution_trace", "authority_shaped_key"),
    ("command_metric", "authority_shaped_key"),
    ("revoke_batch", "authority_shaped_key"),
    ("revocation_note", "authority_shaped_key"),
    ("callback_url_value", "authority_shaped_key"),
    ("redirect_uri_config", "authority_shaped_key"),
    ("customerrecordidvalue", "pii_shaped_key"),
    ("apiuserkeyhash", "secret_shaped_key"),
    ("accesssessionkeyvalue", "secret_shaped_key"),
)
NEUTRAL_GROUP_CASES: Final[tuple[CompositeCase, ...]] = (
    (("api", "user", "key", "hash"), "secret_shaped_key"),
    (("key", "user", "hash", "api"), "secret_shaped_key"),
    (("access", "session", "key", "value"), "secret_shaped_key"),
    (("customer", "record", "id", "value"), "pii_shaped_key"),
    (("id", "record", "subscriber", "hash"), "pii_shaped_key"),
    (("push", "cell", "config", "value"), "authority_shaped_key"),
    (("payload", "cell", "push", "value"), "authority_shaped_key"),
    (("apply", "cell", "network", "value"), "authority_shaped_key"),
    (("config", "cell", "apply", "value"), "authority_shaped_key"),
)
SAFE_FALSE_POSITIVES: Final = (
    "security_level",
    "duration_ms",
    "rapid_key",
    "metric_id",
    "metric_key",
    "shellfish_count",
    "commandment_count",
    "tokenization_mode",
    "executioner_state",
    "config_history",
    "ue_cohort_id",
)
SAFE_EXACT_KEYS: Final = (
    "shellfish_count",
    "commandment_count",
    "tokenization_mode",
    "executioner_state",
    "config_history",
    "ue_cohort_id",
)
URL_URI_STEMS: Final = ("url", "uri")
URL_URI_SAFE_EXCEPTIONS: Final = (
    "security_level",
    "duration_ms",
    "curiosity_score",
    "purity_index",
    "jurisdiction_code",
    "flourish_count",
    "maturity_score",
)
SEMANTIC_ERROR_CODES: Final = frozenset(
    ("pii_shaped_key", "authority_shaped_key", "secret_shaped_key")
)
SAFE_TRANSFORM_CASES: Final = (
    ("security", "level"),
    ("duration", "ms"),
    ("rapid", "key"),
    ("metric", "id"),
    ("metric", "key"),
    ("shellfish", "count"),
    ("commandment", "count"),
    ("tokenization", "mode"),
    ("executioner", "state"),
    ("config", "history"),
    ("ue", "cohort", "id"),
)


@unique
class Boundary(StrEnum):
    ROOT = "root"
    EXTENSIONS = "extensions"
    NESTED = "nested"


def _key_forms(tokens: tuple[str, ...]) -> tuple[str, ...]:
    camel = tokens[0] + "".join(token.title() for token in tokens[1:])
    return (
        "_".join(tokens),
        "-".join(tokens),
        camel,
        "".join(tokens),
        "_".join(tokens).upper(),
    )


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
            payload["extensions"] = {"schema_version": "1.0", "values": {key: "synthetic"}}
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


def _assert_rejected(key: str, expected_code: str) -> None:
    for boundary in Boundary:
        with pytest.raises(ValidationError) as caught:
            _validate_at_boundary(key, boundary)
        assert expected_code in {item["type"] for item in caught.value.errors()}, (
            f"{key}@{boundary.value}"
        )


@pytest.mark.parametrize(("stem", "expected_code"), DANGEROUS_STEM_CASES)
def test_dangerous_stem_rejects_at_prefix_middle_and_suffix(
    stem: str,
    expected_code: str,
) -> None:
    embeddings = ((stem, "metric"), ("metric", stem, "value"), ("metric", stem))
    for tokens in embeddings:
        for key in _key_forms(tokens):
            _assert_rejected(key, expected_code)


@pytest.mark.parametrize("stem", URL_URI_STEMS)
def test_url_uri_stem_rejects_at_prefix_middle_and_suffix(stem: str) -> None:
    embeddings = ((stem, "metric"), ("metric", stem, "value"), ("metric", stem))
    for tokens in embeddings:
        for key in _key_forms(tokens):
            _assert_rejected(key, "authority_shaped_key")


@pytest.mark.parametrize(("key", "expected_code"), REVIEWER_CASES)
def test_reviewer_key_is_rejected_recursively(key: str, expected_code: str) -> None:
    _assert_rejected(key, expected_code)


@pytest.mark.parametrize(("tokens", "expected_code"), NEUTRAL_GROUP_CASES)
def test_neutral_tokens_cannot_split_unordered_group(
    tokens: tuple[str, ...],
    expected_code: str,
) -> None:
    for key in _key_forms(tokens):
        _assert_rejected(key, expected_code)


@pytest.mark.parametrize("key", SAFE_FALSE_POSITIVES)
def test_false_positive_corpus_remains_semantically_safe(key: str) -> None:
    validate_semantic_key(key)
    _validate_at_boundary(key, Boundary.EXTENSIONS)
    _validate_at_boundary(key, Boundary.NESTED)


@pytest.mark.parametrize("tokens", SAFE_TRANSFORM_CASES)
def test_false_positive_corpus_survives_key_transformations(tokens: tuple[str, ...]) -> None:
    for key in _key_forms(tokens):
        validate_semantic_key(key)


@pytest.mark.parametrize("safe_key", URL_URI_SAFE_EXCEPTIONS)
def test_url_uri_natural_word_exception_is_exact(safe_key: str) -> None:
    validate_semantic_key(safe_key)
    _validate_at_boundary(safe_key, Boundary.EXTENSIONS)
    _validate_at_boundary(safe_key, Boundary.NESTED)
    for attack in (f"url_{safe_key}", f"{safe_key}_uri", f"url_{safe_key}_uri"):
        _assert_rejected(attack, "authority_shaped_key")


@pytest.mark.parametrize("safe_key", SAFE_EXACT_KEYS)
def test_material_added_to_safe_exception_is_rejected(safe_key: str) -> None:
    attacks = (
        f"customer_record_{safe_key}",
        f"{safe_key}_shell_request",
        f"password_value_{safe_key}",
    )
    for key in attacks:
        for boundary in Boundary:
            with pytest.raises(ValidationError) as caught:
                _validate_at_boundary(key, boundary)
            observed = {item["type"] for item in caught.value.errors()}
            assert observed & SEMANTIC_ERROR_CODES, f"{key}@{boundary.value}"
