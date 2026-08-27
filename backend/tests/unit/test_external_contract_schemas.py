from __future__ import annotations

import json
import subprocess
import sys
from typing import TYPE_CHECKING, Final

import pytest
import typer
from pydantic import TypeAdapter, ValidationError

from telco_twin.contract_validation import validate_contract
from telco_twin.domain.build_info import (
    EMPTY_CANONICAL_ARTIFACT_HASH,
    BuildInfo,
    ServiceBuildInfo,
    UiBuildInfo,
)

from .contract_cases import APPROVAL_FIXTURES, REPO_ROOT
from .contract_payloads import JsonObject, build_identity_payloads, valid_domain_cases

if TYPE_CHECKING:
    from pathlib import Path

JSON_OBJECT_ADAPTER: Final[TypeAdapter[JsonObject]] = TypeAdapter(JsonObject)
CHECK_JSONSCHEMA: Final = "check-jsonschema"


def _read_json(path: Path) -> JsonObject:
    return JSON_OBJECT_ADAPTER.validate_json(path.read_bytes())


def _write_json(path: Path, value: JsonObject) -> None:
    _ = path.write_text(json.dumps(value), encoding="utf-8")


def _check_schema(schema_name: str, input_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        (
            CHECK_JSONSCHEMA,
            "--schemafile",
            str(REPO_ROOT / f"specs/schemas/{schema_name}.schema.json"),
            str(input_path),
        ),
        check=False,
        capture_output=True,
        text=True,
    )


def _run_project_validator(
    schema_name: str,
    input_path: Path,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        (
            sys.executable,
            str(REPO_ROOT / "scripts/validate_contract.py"),
            "--schema",
            schema_name,
            "--input",
            str(input_path),
        ),
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize("nonce", ["A" * 21, "A" * 23, ("A" * 21) + "="])
def test_external_request_schema_rejects_noncanonical_nonce(
    tmp_path: Path,
    nonce: str,
) -> None:
    payload = _read_json(APPROVAL_FIXTURES / "test-approval-request.json")
    payload["nonce"] = nonce
    input_path = tmp_path / "request.json"
    _write_json(input_path, payload)

    result = _check_schema("approval-request", input_path)

    assert result.returncode != 0, result.stdout


def test_external_certificate_schema_rejects_wrong_ed25519_lengths(
    tmp_path: Path,
) -> None:
    payload = _read_json(APPROVAL_FIXTURES / "test-session-certificate.json")
    jwk = JSON_OBJECT_ADAPTER.validate_python(payload["session_public_key_jwk"])
    jwk["x"] = "A" * 42
    payload["session_public_key_jwk"] = jwk
    payload["certificate_signature"] = "A" * 85
    input_path = tmp_path / "certificate.json"
    _write_json(input_path, payload)

    result = _check_schema("session-key-certificate", input_path)

    assert result.returncode != 0, result.stdout


def test_external_public_jwk_schema_rejects_private_d(tmp_path: Path) -> None:
    payload = _read_json(APPROVAL_FIXTURES / "test-session-certificate.json")
    jwk = JSON_OBJECT_ADAPTER.validate_python(payload["session_public_key_jwk"])
    jwk["d"] = "A" * 43
    payload["session_public_key_jwk"] = jwk
    input_path = tmp_path / "private-jwk.json"
    _write_json(input_path, payload)

    result = _check_schema("session-key-certificate", input_path)

    assert result.returncode != 0, result.stdout


def test_external_proof_schema_rejects_wrong_signature_length(tmp_path: Path) -> None:
    payload = _read_json(APPROVAL_FIXTURES / "test-approval-proof.json")
    payload["proof_signature"] = "A" * 87
    input_path = tmp_path / "proof.json"
    _write_json(input_path, payload)

    result = _check_schema("approval-proof", input_path)

    assert result.returncode != 0, result.stdout


@pytest.mark.parametrize(
    ("schema_name", "model"),
    [("service-build-info", ServiceBuildInfo), ("ui-build-info", UiBuildInfo)],
)
def test_external_build_schema_rejects_array_trust_root_hash(
    tmp_path: Path,
    schema_name: str,
    model: type[BuildInfo],
) -> None:
    service, ui = build_identity_payloads(EMPTY_CANONICAL_ARTIFACT_HASH)
    payload = {"service-build-info": service, "ui-build-info": ui}[schema_name]
    payload["trusted_root_hashes"] = []
    input_path = tmp_path / f"{schema_name}.json"
    _write_json(input_path, payload)

    result = _check_schema(schema_name, input_path)

    with pytest.raises(ValidationError):
        _ = model.model_validate(payload)
    assert result.returncode != 0, result.stdout


@pytest.mark.parametrize(
    ("schema_name", "model"),
    [("service-build-info", ServiceBuildInfo), ("ui-build-info", UiBuildInfo)],
)
def test_external_build_schema_accepts_not_applicable_trust_root_hash(
    tmp_path: Path,
    schema_name: str,
    model: type[BuildInfo],
) -> None:
    service, ui = build_identity_payloads(EMPTY_CANONICAL_ARTIFACT_HASH)
    payload = {"service-build-info": service, "ui-build-info": ui}[schema_name]
    payload["trusted_root_hashes"] = EMPTY_CANONICAL_ARTIFACT_HASH
    input_path = tmp_path / f"{schema_name}.json"
    _write_json(input_path, payload)

    result = _check_schema(schema_name, input_path)

    assert model.model_validate(payload).trusted_root_hashes == EMPTY_CANONICAL_ARTIFACT_HASH
    assert result.returncode == 0, result.stderr


def test_ttl_limitation_is_annotated_and_project_validator_is_normative(
    tmp_path: Path,
) -> None:
    payload = _read_json(APPROVAL_FIXTURES / "test-approval-request.json")
    payload["expires_at"] = "2026-08-27T00:02:00Z"
    input_path = tmp_path / "request-120s.json"
    _write_json(input_path, payload)
    schema = _read_json(REPO_ROOT / "specs/schemas/approval-request.schema.json")

    structural = _check_schema("approval-request", input_path)
    project = _run_project_validator("approval-request", input_path)

    assert structural.returncode == 0
    assert schema["x-telco-twin-invariants"] == [
        {
            "code": "ttl_60_seconds",
            "kind": "duration_seconds",
            "start_field": "requested_at",
            "end_field": "expires_at",
            "seconds": 60,
            "json_schema_support": "annotation_only",
            "enforced_by": "scripts/validate_contract.py",
        }
    ]
    assert project.returncode == 3
    assert "contract-invalid:approval-request:ttl_60_seconds" in project.stderr


def test_approval_proof_schema_declares_equal_certificate_window_consequence() -> None:
    schema = _read_json(REPO_ROOT / "specs/schemas/approval-proof.schema.json")

    assert schema["x-telco-twin-certificate-window"] == {
        "code": "proof_certificate_window",
        "kind": "contained_interval",
        "proof_start_field": "approved_at",
        "proof_end_field": "expires_at",
        "certificate_start_field": "issued_at",
        "certificate_end_field": "expires_at",
        "ttl_consequence": "equal_window_required_when_both_are_60_seconds",
        "json_schema_support": "annotation_only",
        "enforced_by": "scripts/validate_contract.py",
    }


def test_semantic_key_limitation_is_annotated_and_project_validator_is_normative(
    tmp_path: Path,
) -> None:
    _, scenario_payload = next(
        case for case in valid_domain_cases() if case[0].__name__ == "Scenario"
    )
    scenario_payload["extensions"] = {
        "schema_version": "1.0",
        "values": {"customer_id": "synthetic"},
    }
    input_path = tmp_path / "scenario-semantic-key.json"
    _write_json(input_path, scenario_payload)
    schema = _read_json(REPO_ROOT / "specs/schemas/scenario.schema.json")

    structural = _check_schema("scenario", input_path)
    project = _run_project_validator("scenario", input_path)
    key_policy = JSON_OBJECT_ADAPTER.validate_python(schema["x-telco-twin-key-policy"])

    assert structural.returncode == 0
    assert key_policy["recursive"] is True
    assert key_policy["json_schema_support"] == "annotation_only"
    assert key_policy["enforced_by"] == "scripts/validate_contract.py"
    assert project.returncode == 3
    assert "contract-invalid:scenario:pii_shaped_key" in project.stderr


def test_project_validator_accepts_current_annotations(
    capsys: pytest.CaptureFixture[str],
) -> None:
    validate_contract(
        "approval-request",
        APPROVAL_FIXTURES / "test-approval-request.json",
        REPO_ROOT / "specs/schemas",
    )

    assert capsys.readouterr().out == "contract-valid:approval-request\n"


def test_project_validator_rejects_stale_invariant_annotation(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    schema = _read_json(REPO_ROOT / "specs/schemas/approval-request.schema.json")
    schema["x-telco-twin-invariants"] = []
    schema_dir = tmp_path / "schemas"
    schema_dir.mkdir()
    _write_json(schema_dir / "approval-request.schema.json", schema)

    with pytest.raises(typer.Exit) as caught:
        validate_contract(
            "approval-request",
            APPROVAL_FIXTURES / "test-approval-request.json",
            schema_dir,
        )

    assert caught.value.exit_code == 3
    assert capsys.readouterr().err == ("contract-schema-annotations-stale:approval-request\n")


def test_separator_free_key_policy_is_declared_and_normatively_rejected(
    tmp_path: Path,
) -> None:
    _, payload = next(case for case in valid_domain_cases() if case[0].__name__ == "Scenario")
    payload["extensions"] = {
        "schema_version": "1.0",
        "values": {"customerid": "synthetic"},
    }
    input_path = tmp_path / "scenario-collapsed-key.json"
    _write_json(input_path, payload)
    schema = _read_json(REPO_ROOT / "specs/schemas/scenario.schema.json")
    key_policy = JSON_OBJECT_ADAPTER.validate_python(schema["x-telco-twin-key-policy"])

    structural = _check_schema("scenario", input_path)
    project = _run_project_validator("scenario", input_path)

    assert structural.returncode == 0
    assert key_policy["collapsed_pii_keys"] == [
        "customerid",
        "emailaddress",
        "subscriberid",
    ]
    assert key_policy["collapsed_authority_keys"] == [
        "applytonetwork",
        "pushpayload",
        "shellcommand",
    ]
    assert key_policy["collapsed_secret_keys"] == ["accesstoken"]
    assert project.returncode == 3
    assert "contract-invalid:scenario:pii_shaped_key" in project.stderr
