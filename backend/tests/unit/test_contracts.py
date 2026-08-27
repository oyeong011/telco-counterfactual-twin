from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

import pytest
import rfc8785
from nacl.signing import SigningKey
from pydantic import JsonValue, TypeAdapter, ValidationError

from telco_twin.domain.approval import (
    ApprovalProof,
    ApprovalRequest,
    ContractErrorCode,
    ContractViolationError,
    Ed25519Jwk,
    Environment,
    canonical_model_bytes,
    certificate_hash,
    certificate_signing_bytes,
    descriptor_hash,
    proof_hash,
    proof_signing_bytes,
    validate_approval_chain,
    validate_root_trust,
)
from telco_twin.domain.build_info import (
    EMPTY_CANONICAL_ARTIFACT_HASH,
    DigestScope,
    ServiceBuildInfo,
    UiBuildInfo,
)
from telco_twin.domain.topology import Topology
from telco_twin.schema_export import CONTRACT_MODELS, render_schema

from .contract_cases import (
    APPROVAL_FIXTURES,
    REPO_ROOT,
    SCHEMA_NAMES,
    InvalidContractCase,
    approval_context,
    invalid_domain_cases,
    load_approval_bundle,
)
from .contract_payloads import (
    build_identity_payloads,
    topology_payload,
    valid_domain_cases,
)

if TYPE_CHECKING:
    from pathlib import Path

JSON_OBJECT_ADAPTER: Final[TypeAdapter[dict[str, JsonValue]]] = TypeAdapter(dict[str, JsonValue])


def test_valid_domain_contracts_round_trip() -> None:
    for model, payload in valid_domain_cases():
        parsed = model.model_validate(payload)
        assert model.model_validate_json(parsed.model_dump_json()) == parsed
        with pytest.raises(ValidationError, match="extra_forbidden"):
            _ = model.model_validate({**payload, "unknown": "forbidden"})


@pytest.mark.parametrize("case", invalid_domain_cases())
def test_domain_contracts_reject_unsafe_shapes(case: InvalidContractCase) -> None:
    with pytest.raises(ValidationError) as caught:
        _ = case.model.model_validate(case.payload)
    assert case.error_code in {item["type"] for item in caught.value.errors()}


def test_approval_fixture_round_trip_and_chain() -> None:
    bundle = load_approval_bundle()
    validate_approval_chain(bundle.proof, approval_context())
    assert descriptor_hash(bundle.root) == bundle.root.descriptor_hash
    assert certificate_hash(bundle.certificate) == bundle.proof.certificate_hash
    assert proof_hash(bundle.proof) == (
        "e45c5a5b95d29c737c34c6702425affb79f92c639cfff83efeec31ea35b4a961"
    )
    assert certificate_signing_bytes(bundle.certificate).startswith(b"telco-twin/session-cert/v1\0")
    assert proof_signing_bytes(bundle.proof).startswith(b"telco-twin/approval-proof/v1\0")


def test_approval_rejects_tampering_expiry_and_replay() -> None:
    context = approval_context()
    proof = load_approval_bundle().proof
    alternate_prefix = "A" if proof.proof_signature[0] != "A" else "B"
    certificate_prefix = "A" if context.certificate.certificate_signature[0] != "A" else "B"
    cases = (
        (
            proof.model_copy(update={"session_id": "session-other"}),
            context,
            ContractErrorCode.APPROVAL_BINDING_MISMATCH,
        ),
        (
            proof.model_copy(update={"approval_request_id": "approval-request-other"}),
            context,
            ContractErrorCode.APPROVAL_BINDING_MISMATCH,
        ),
        (
            proof.model_copy(update={"patch_hash": "9" * 64}),
            context,
            ContractErrorCode.APPROVAL_BINDING_MISMATCH,
        ),
        (
            proof.model_copy(update={"certificate_hash": "8" * 64}),
            context,
            ContractErrorCode.CERTIFICATE_HASH_MISMATCH,
        ),
        (
            proof,
            replace(
                context,
                certificate=context.certificate.model_copy(
                    update={
                        "certificate_signature": (
                            certificate_prefix + context.certificate.certificate_signature[1:]
                        )
                    }
                ),
            ),
            ContractErrorCode.CERTIFICATE_SIGNATURE_INVALID,
        ),
        (
            proof.model_copy(
                update={"proof_signature": alternate_prefix + proof.proof_signature[1:]}
            ),
            context,
            ContractErrorCode.PROOF_SIGNATURE_INVALID,
        ),
        (
            proof,
            replace(context, now=datetime(2026, 8, 27, 0, 1, 1, tzinfo=UTC)),
            ContractErrorCode.APPROVAL_EXPIRED,
        ),
        (
            proof,
            replace(context, now=datetime(2026, 8, 26, 23, 59, 59, tzinfo=UTC)),
            ContractErrorCode.APPROVAL_NOT_YET_VALID,
        ),
        (
            proof,
            replace(context, consumed_nonces=frozenset({proof.nonce})),
            ContractErrorCode.NONCE_REPLAYED,
        ),
    )
    for candidate, candidate_context, expected in cases:
        with pytest.raises(ContractViolationError) as caught:
            validate_approval_chain(candidate, candidate_context)
        assert caught.value.code is expected


def test_approval_forbids_execution_and_revocation_fields() -> None:
    proof = load_approval_bundle().proof
    for field in ("execution", "revocation", "proof_hash"):
        with pytest.raises(ValidationError, match="extra_forbidden"):
            _ = ApprovalProof.model_validate({**proof.model_dump(mode="json"), field: {}})


def test_approval_primitives_production_trust_and_rfc8037_vector() -> None:
    root = load_approval_bundle().root
    with pytest.raises(ContractViolationError) as caught:
        validate_root_trust(
            root,
            Environment.PRODUCTION,
            frozenset({root.descriptor_hash}),
        )
    assert caught.value.code is ContractErrorCode.TEST_ROOT_FORBIDDEN
    with pytest.raises(ContractViolationError) as untrusted:
        validate_root_trust(root, Environment.TEST, frozenset())
    assert untrusted.value.code is ContractErrorCode.ROOT_UNTRUSTED
    invalid_fields = (
        ("nonce", "AAECAwQFBgcICQoLDA0ODw==", "base64url_no_padding"),
        ("patch_hash", "A" * 64, "string_pattern_mismatch"),
        ("request_id", "INVALID_ID", "string_pattern_mismatch"),
    )
    for field, value, code in invalid_fields:
        payload = JSON_OBJECT_ADAPTER.validate_json(
            (APPROVAL_FIXTURES / "test-approval-request.json").read_bytes()
        )
        payload[field] = value
        with pytest.raises(ValidationError) as invalid:
            _ = ApprovalRequest.model_validate(payload)
        assert code in {item["type"] for item in invalid.value.errors()}
    invalid_ttl = JSON_OBJECT_ADAPTER.validate_json(
        (APPROVAL_FIXTURES / "test-approval-request.json").read_bytes()
    )
    invalid_ttl["expires_at"] = "2026-08-27T00:01:01Z"
    with pytest.raises(ValidationError) as ttl_error:
        _ = ApprovalRequest.model_validate(invalid_ttl)
    assert "ttl_60_seconds" in {item["type"] for item in ttl_error.value.errors()}
    with pytest.raises(ValidationError) as invalid_jwk:
        _ = Ed25519Jwk.model_validate({"kty": "OKP", "crv": "Ed25519", "x": "AA"})
    assert "ed25519_jwk" in {item["type"] for item in invalid_jwk.value.errors()}
    seed = bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60")
    expected = (
        "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490155"
        "5fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"
    )
    assert SigningKey(seed).sign(b"").signature.hex() == expected


def test_rfc8785_rejects_values_outside_i_json() -> None:
    with pytest.raises(rfc8785.FloatDomainError):
        _ = rfc8785.dumps(float("nan"))
    with pytest.raises(rfc8785.FloatDomainError):
        _ = rfc8785.dumps(float("inf"))
    with pytest.raises(rfc8785.IntegerDomainError):
        _ = rfc8785.dumps(2**53)


def test_build_identity_component_boundaries_and_empty_hash() -> None:
    service_payload, ui_payload = build_identity_payloads(EMPTY_CANONICAL_ARTIFACT_HASH)
    service = ServiceBuildInfo.model_validate(service_payload)
    ui = UiBuildInfo.model_validate(ui_payload)
    assert service.digest_scope is DigestScope.REGISTRY_MANIFEST
    assert ui.asset_manifest_hash == "7" * 64
    assert EMPTY_CANONICAL_ARTIFACT_HASH == (
        "ca3d163bab055381827226140568f3bef7eaac187cebd76878e0b63e9e442356"
    )
    with pytest.raises(ValidationError, match="extra_forbidden"):
        _ = UiBuildInfo.model_validate(
            {
                **ui.model_dump(mode="json"),
                "image_digest": f"sha256:{'8' * 64}",
                "digest_scope": "local",
            }
        )
    with pytest.raises(ValidationError, match="extra_forbidden"):
        _ = ServiceBuildInfo.model_validate(
            {**service.model_dump(mode="json"), "asset_manifest_hash": "9" * 64}
        )


def test_exported_json_schemas_match_pydantic_models() -> None:
    assert tuple(CONTRACT_MODELS) == SCHEMA_NAMES
    for name, model in CONTRACT_MODELS.items():
        expected = render_schema(name, model)
        assert (REPO_ROOT / f"specs/schemas/{name}.schema.json").read_bytes() == expected


def test_domain_and_approval_canonical_bytes_are_cross_process_stable(
    tmp_path: Path,
) -> None:
    topology = Topology.model_validate(topology_payload())
    topology_path = tmp_path / "topology.json"
    _ = topology_path.write_text(topology.model_dump_json(), encoding="utf-8")
    direct = canonical_model_bytes(topology).hex()
    code = (
        "from pathlib import Path;"
        "from telco_twin.domain.approval import canonical_model_bytes;"
        "from telco_twin.domain.topology import Topology;"
        "import sys;"
        "value=Topology.model_validate_json(Path(sys.argv[1]).read_text());"
        "print(canonical_model_bytes(value).hex())"
    )
    outputs: list[str] = []
    for seed_value in ("1", "987654"):
        environment = os.environ.copy()
        environment["PYTHONHASHSEED"] = seed_value
        result = subprocess.run(
            [sys.executable, "-c", code, str(topology_path)],
            cwd=REPO_ROOT,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )
        outputs.append(result.stdout.strip())
    assert outputs == [direct, direct]
