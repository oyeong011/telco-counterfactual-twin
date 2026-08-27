"""Approval key parsing, issuance, and evidence-ledger edge tests."""

import base64
import hashlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import anyio
import pytest
import rfc8785
from nacl.signing import SigningKey

from telco_twin.approval.authority import (
    ApprovalProofIssue,
    ApprovalRequestIssue,
    AuthorityLoadError,
    AuthorityLoadErrorCode,
    AuthorityMode,
    SessionIssue,
    issue_approval_request,
    load_approval_authority,
)
from telco_twin.approval.crypto import (
    SigningMaterialError,
    SigningMaterialErrorCode,
    parse_signing_key,
    public_key_fingerprint,
)
from telco_twin.approval.state_machine import (
    ApprovalStateError,
    ApprovalStateErrorCode,
    ApprovalStateMachine,
)
from telco_twin.domain.approval import (
    ApprovalDecision,
    ApprovalValidationContext,
    Environment,
    RootDescriptor,
    encode_base64url,
)
from telco_twin.domain.canonical import canonical_model_bytes
from telco_twin.safety.local_policy import PolicyEvaluation

from .test_approval_state import approval_chain

if TYPE_CHECKING:
    from pydantic import JsonValue


def _production_descriptor(key: SigningKey) -> RootDescriptor:
    payload: dict[str, JsonValue] = {
        "root_key_id": "production-edge-root",
        "algorithm": "Ed25519",
        "public_key_jwk": {
            "kty": "OKP",
            "crv": "Ed25519",
            "x": encode_base64url(bytes(key.verify_key)),
        },
        "environment": "production",
        "not_before": "2026-01-01T00:00:00Z",
        "not_after": "2027-01-01T00:00:00Z",
        "schema_version": "1.0",
    }
    payload["descriptor_hash"] = hashlib.sha256(rfc8785.dumps(payload)).hexdigest()
    return RootDescriptor.model_validate(payload)


@pytest.mark.parametrize(
    ("encoded", "code"),
    [
        ("-----BEGIN PRIVATE KEY-----\nAAAA", SigningMaterialErrorCode.PEM),
        (
            "-----BEGIN PRIVATE KEY-----\n***\n-----END PRIVATE KEY-----",
            SigningMaterialErrorCode.PEM,
        ),
        (
            "-----BEGIN PRIVATE KEY-----\n"
            + base64.b64encode(b"\0" * 48).decode()
            + "\n-----END PRIVATE KEY-----",
            SigningMaterialErrorCode.ALGORITHM,
        ),
        ("AQ==", SigningMaterialErrorCode.BASE64URL),
        ("A", SigningMaterialErrorCode.BASE64URL),
        ("AB", SigningMaterialErrorCode.BASE64URL),
        (encode_base64url(b"\0" * 31), SigningMaterialErrorCode.LENGTH),
    ],
)
def test_root_signing_material_parser_rejects_each_malformed_class(
    encoded: str,
    code: SigningMaterialErrorCode,
) -> None:
    # Given: one malformed private-key representation.
    # When: the strict root-key parser receives it.
    with pytest.raises(SigningMaterialError) as caught:
        _ = parse_signing_key(encoded)
    # Then: a stable parser code is returned without material disclosure.
    assert caught.value.code is code
    assert str(caught.value) == code.value


def test_raw_root_key_fingerprint_is_stable() -> None:
    # Given: one valid raw Ed25519 seed.
    key = parse_signing_key(encode_base64url(b"\x55" * 32))
    # When: its public fingerprint is calculated.
    fingerprint = public_key_fingerprint(key)
    # Then: the result is a lowercase SHA-256 identity.
    assert fingerprint == hashlib.sha256(bytes(key.verify_key)).hexdigest()


def test_authority_rejects_out_of_window_session_late_proof_and_bad_nonce() -> None:
    # Given: the committed local authority and one valid short-lived session/request.
    authority = load_approval_authority(AuthorityMode.LOCAL)
    session = authority.issue_session(
        SessionIssue(session_id="session-0001", issued_at="2026-08-27T00:00:00Z")
    )
    request = issue_approval_request(
        ApprovalRequestIssue(
            request_id="approval-request-0001",
            session_id="session-0001",
            patch_hash="a" * 64,
            simulation_hash="b" * 64,
            policy_hash="c" * 64,
            requested_at="2026-08-27T00:00:00Z",
            nonce=b"\x01" * 16,
        )
    )
    # When/Then: each issuance boundary fails with its typed reason.
    with pytest.raises(AuthorityLoadError) as session_error:
        _ = authority.issue_session(
            SessionIssue(session_id="session-late", issued_at="2027-01-01T00:00:00Z")
        )
    assert session_error.value.code is AuthorityLoadErrorCode.SESSION_OUTSIDE_ROOT_WINDOW
    with pytest.raises(AuthorityLoadError) as proof_error:
        _ = session.issue_proof(
            ApprovalProofIssue(
                request=request,
                decision=ApprovalDecision.APPROVED,
                proof_id="approval-proof-late",
                approved_at="2026-08-27T00:00:01Z",
            )
        )
    assert proof_error.value.code is AuthorityLoadErrorCode.PROOF_OUTSIDE_EVIDENCE_WINDOW
    with pytest.raises(AuthorityLoadError) as nonce_error:
        _ = issue_approval_request(
            ApprovalRequestIssue(
                request_id="approval-request-bad-nonce",
                session_id="session-0001",
                patch_hash="a" * 64,
                simulation_hash="b" * 64,
                policy_hash="c" * 64,
                requested_at="2026-08-27T00:00:00Z",
                nonce=b"short",
            )
        )
    assert nonce_error.value.code is AuthorityLoadErrorCode.REQUEST_NONCE_INVALID


def test_production_rejects_missing_descriptor_and_malformed_material(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: production mode first without a descriptor, then with malformed key material.
    with pytest.raises(AuthorityLoadError) as descriptor_error:
        _ = load_approval_authority(AuthorityMode.PRODUCTION)
    assert descriptor_error.value.code is AuthorityLoadErrorCode.ROOT_DESCRIPTOR_MISSING
    descriptor = _production_descriptor(SigningKey(b"\x66" * 32))
    monkeypatch.setenv("APPROVAL_ROOT_KEY_SECRET", "bad")
    # When: production key parsing runs.
    with pytest.raises(AuthorityLoadError) as material_error:
        _ = load_approval_authority(AuthorityMode.PRODUCTION, descriptor)
    # Then: invalid material is distinct from missing authority.
    assert material_error.value.code is AuthorityLoadErrorCode.ROOT_MATERIAL_INVALID


def test_evidence_ledger_rejects_duplicate_unknown_and_context_mismatch() -> None:
    async def scenario() -> None:
        # Given: one pending record and another valid proof sharing only its request ID.
        policy, request, proof, context = approval_chain()
        machine = ApprovalStateMachine()
        _ = await machine.record_request(request, policy)
        with pytest.raises(ApprovalStateError) as duplicate:
            _ = await machine.record_request(request, policy)
        assert duplicate.value.code is ApprovalStateErrorCode.REQUEST_EXISTS
        empty = ApprovalStateMachine()
        with pytest.raises(ApprovalStateError) as unknown:
            _ = await empty.record_proof(proof, context)
        assert unknown.value.code is ApprovalStateErrorCode.REQUEST_UNKNOWN
        authority = load_approval_authority(AuthorityMode.LOCAL)
        session = authority.issue_session(
            SessionIssue(session_id="session-0001", issued_at="2026-08-27T00:00:00Z")
        )
        alternate = issue_approval_request(
            ApprovalRequestIssue(
                request_id=request.request_id,
                session_id=request.session_id,
                patch_hash=request.patch_hash,
                simulation_hash=request.simulation_hash,
                policy_hash=request.policy_hash,
                requested_at=request.requested_at,
                nonce=b"\x03" * 16,
            )
        )
        alternate_proof = session.issue_proof(
            ApprovalProofIssue(
                request=alternate,
                decision=ApprovalDecision.APPROVED,
                proof_id="approval-proof-alternate",
                approved_at=alternate.requested_at,
            )
        )
        alternate_context = ApprovalValidationContext(
            root=authority.descriptor,
            certificate=session.certificate,
            request=alternate,
            environment=Environment.TEST,
            trusted_root_hashes=frozenset({authority.descriptor.descriptor_hash}),
            consumed_nonces=frozenset(),
            now=datetime(2026, 8, 27, 0, 0, 30, tzinfo=UTC),
        )
        with pytest.raises(ApprovalStateError) as mismatch:
            _ = await machine.record_proof(alternate_proof, alternate_context)
        assert mismatch.value.code is ApprovalStateErrorCode.REQUEST_CONTEXT_MISMATCH
        assert await machine.get(request.request_id) is not None
        assert str(mismatch.value) == ApprovalStateErrorCode.REQUEST_CONTEXT_MISMATCH.value

    anyio.run(scenario)


def test_changed_policy_definition_never_creates_pending_state() -> None:
    async def scenario() -> None:
        # Given: a self-consistent policy result carrying a different definition hash.
        policy, request, _, _ = approval_chain()
        draft = policy.model_copy(
            update={"policy_definition_hash": "d" * 64, "policy_hash": "0" * 64}
        )
        forged = draft.model_copy(
            update={
                "policy_hash": hashlib.sha256(
                    canonical_model_bytes(draft, exclude=frozenset({"policy_hash"}))
                ).hexdigest()
            }
        )
        validated = PolicyEvaluation.model_validate_json(forged.model_dump_json())
        changed_request = request.model_copy(update={"policy_hash": validated.policy_hash})
        machine = ApprovalStateMachine()
        # When: request admission sees the changed policy definition.
        with pytest.raises(ApprovalStateError) as caught:
            _ = await machine.record_request(changed_request, validated)
        # Then: a rehashed but changed policy definition still fails closed.
        assert caught.value.code is ApprovalStateErrorCode.EVIDENCE_BINDING_MISMATCH

    anyio.run(scenario)
