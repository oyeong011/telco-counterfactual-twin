from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import typer
from pydantic import ValidationError

from telco_twin.contract_validation import validate_contract
from telco_twin.domain.build_info import (
    EMPTY_CANONICAL_ARTIFACT_HASH,
    BuildInfo,
    ServiceBuildInfo,
    UiBuildInfo,
)

from .contract_cases import APPROVAL_FIXTURES, REPO_ROOT
from .contract_payloads import build_identity_payloads, valid_domain_cases
from .schema_test_support import (
    JSON_OBJECT_ADAPTER,
    check_schema,
    read_json,
    run_project_validator,
    write_json,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("nonce", ["A" * 21, "A" * 23, ("A" * 21) + "="])
def test_external_request_schema_rejects_noncanonical_nonce(
    tmp_path: Path,
    nonce: str,
) -> None:
    payload = read_json(APPROVAL_FIXTURES / "test-approval-request.json")
    payload["nonce"] = nonce
    input_path = tmp_path / "request.json"
    write_json(input_path, payload)

    result = check_schema("approval-request", input_path)

    assert result.returncode != 0, result.stdout


def test_external_certificate_schema_rejects_wrong_ed25519_lengths(
    tmp_path: Path,
) -> None:
    payload = read_json(APPROVAL_FIXTURES / "test-session-certificate.json")
    jwk = JSON_OBJECT_ADAPTER.validate_python(payload["session_public_key_jwk"])
    jwk["x"] = "A" * 42
    payload["session_public_key_jwk"] = jwk
    payload["certificate_signature"] = "A" * 85
    input_path = tmp_path / "certificate.json"
    write_json(input_path, payload)

    result = check_schema("session-key-certificate", input_path)

    assert result.returncode != 0, result.stdout


def test_external_public_jwk_schema_rejects_private_d(tmp_path: Path) -> None:
    payload = read_json(APPROVAL_FIXTURES / "test-session-certificate.json")
    jwk = JSON_OBJECT_ADAPTER.validate_python(payload["session_public_key_jwk"])
    jwk["d"] = "A" * 43
    payload["session_public_key_jwk"] = jwk
    input_path = tmp_path / "private-jwk.json"
    write_json(input_path, payload)

    result = check_schema("session-key-certificate", input_path)

    assert result.returncode != 0, result.stdout


def test_external_proof_schema_rejects_wrong_signature_length(tmp_path: Path) -> None:
    payload = read_json(APPROVAL_FIXTURES / "test-approval-proof.json")
    payload["proof_signature"] = "A" * 87
    input_path = tmp_path / "proof.json"
    write_json(input_path, payload)

    result = check_schema("approval-proof", input_path)

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
    write_json(input_path, payload)

    result = check_schema(schema_name, input_path)

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
    write_json(input_path, payload)

    result = check_schema(schema_name, input_path)

    assert model.model_validate(payload).trusted_root_hashes == EMPTY_CANONICAL_ARTIFACT_HASH
    assert result.returncode == 0, result.stderr


def test_ttl_limitation_is_annotated_and_project_validator_is_normative(
    tmp_path: Path,
) -> None:
    payload = read_json(APPROVAL_FIXTURES / "test-approval-request.json")
    payload["expires_at"] = "2026-08-27T00:02:00Z"
    input_path = tmp_path / "request-120s.json"
    write_json(input_path, payload)
    schema = read_json(REPO_ROOT / "specs/schemas/approval-request.schema.json")

    structural = check_schema("approval-request", input_path)
    project = run_project_validator("approval-request", input_path)

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
    schema = read_json(REPO_ROOT / "specs/schemas/approval-proof.schema.json")

    assert schema["x-telco-twin-certificate-window"] == {
        "code": "proof-certificate-window",
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
    write_json(input_path, scenario_payload)
    schema = read_json(REPO_ROOT / "specs/schemas/scenario.schema.json")

    structural = check_schema("scenario", input_path)
    project = run_project_validator("scenario", input_path)
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
    schema = read_json(REPO_ROOT / "specs/schemas/approval-request.schema.json")
    schema["x-telco-twin-invariants"] = []
    schema_dir = tmp_path / "schemas"
    schema_dir.mkdir()
    write_json(schema_dir / "approval-request.schema.json", schema)

    with pytest.raises(typer.Exit) as caught:
        validate_contract(
            "approval-request",
            APPROVAL_FIXTURES / "test-approval-request.json",
            schema_dir,
        )

    assert caught.value.exit_code == 3
    assert capsys.readouterr().err == ("contract-schema-annotations-stale:approval-request\n")
