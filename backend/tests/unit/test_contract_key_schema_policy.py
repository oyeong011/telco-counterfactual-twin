from __future__ import annotations

from typing import TYPE_CHECKING, Final

from pydantic import TypeAdapter

from .contract_cases import REPO_ROOT
from .contract_payloads import valid_domain_cases
from .schema_test_support import (
    JSON_OBJECT_ADAPTER,
    check_schema,
    read_json,
    run_project_validator,
    write_json,
)

if TYPE_CHECKING:
    from pathlib import Path

LEXEME_GROUPS_ADAPTER: Final[TypeAdapter[list[list[list[str]]]]] = TypeAdapter(
    list[list[list[str]]]
)


def test_separator_free_key_policy_is_declared_and_normatively_rejected(
    tmp_path: Path,
) -> None:
    _, payload = next(case for case in valid_domain_cases() if case[0].__name__ == "Scenario")
    payload["extensions"] = {
        "schema_version": "1.0",
        "values": {"callbackurl": "synthetic"},
    }
    input_path = tmp_path / "scenario-collapsed-key.json"
    write_json(input_path, payload)
    schema = read_json(REPO_ROOT / "specs/schemas/scenario.schema.json")
    key_policy = JSON_OBJECT_ADAPTER.validate_python(schema["x-telco-twin-key-policy"])
    authority_groups = LEXEME_GROUPS_ADAPTER.validate_python(
        key_policy["authority_unordered_groups"]
    )
    secret_groups = LEXEME_GROUPS_ADAPTER.validate_python(key_policy["secret_unordered_groups"])

    structural = check_schema("scenario", input_path)
    project = run_project_validator("scenario", input_path)

    assert structural.returncode == 0
    assert key_policy["normalization"] == "lowercase_alphanumeric"
    assert key_policy["pii_direct_stems"] == [
        "customer",
        "email",
        "gpsi",
        "imei",
        "imsi",
        "msisdn",
        "phone",
        "subscriber",
        "supi",
    ]
    assert key_policy["authority_direct_stems"] == [
        "command",
        "execute",
        "execution",
        "revoke",
        "revocation",
        "shell",
    ]
    assert key_policy["secret_direct_stems"] == [
        "credential",
        "passwd",
        "password",
        "secret",
        "token",
    ]
    assert key_policy["authority_url_uri_stems"] == ["uri", "url"]
    assert key_policy["pii_unordered_groups"] == [
        [
            ["customer", "subscriber"],
            ["id", "identifier", "identifiers", "identity"],
        ]
    ]
    assert [["push"], ["config", "network", "payload"]] in authority_groups
    assert [["api"], ["key", "secret", "token"]] in secret_groups
    assert [["access"], ["key", "secret", "token"]] in secret_groups
    assert key_policy["safe_exact_keys"] == [
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
    ]
    assert project.returncode == 3
    assert "contract-invalid:scenario:authority_shaped_key" in project.stderr
