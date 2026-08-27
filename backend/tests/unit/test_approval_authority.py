"""Root and root-certified session approval authority tests."""

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

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
from telco_twin.approval.crypto import parse_signing_key
from telco_twin.domain.approval import (
    ApprovalDecision,
    ApprovalValidationContext,
    Environment,
    RootDescriptor,
    certificate_hash,
    certificate_signing_bytes,
    decode_base64url,
    encode_base64url,
    proof_signing_bytes,
    validate_approval_chain,
)

if TYPE_CHECKING:
    from pydantic import JsonValue


def production_descriptor(signing_key: SigningKey) -> RootDescriptor:
    payload: dict[str, JsonValue] = {
        "root_key_id": "production-root-0001",
        "algorithm": "Ed25519",
        "public_key_jwk": {
            "kty": "OKP",
            "crv": "Ed25519",
            "x": encode_base64url(bytes(signing_key.verify_key)),
        },
        "environment": "production",
        "not_before": "2026-01-01T00:00:00Z",
        "not_after": "2027-01-01T00:00:00Z",
        "schema_version": "1.0",
    }
    payload["descriptor_hash"] = hashlib.sha256(rfc8785.dumps(payload)).hexdigest()
    return RootDescriptor.model_validate(payload)


def _trust_descriptor(
    monkeypatch: pytest.MonkeyPatch,
    descriptor: RootDescriptor,
) -> None:
    monkeypatch.setenv(
        "APPROVAL_TRUSTED_ROOT_HASHES_JSON",
        f'["{descriptor.descriptor_hash}"]',
    )


def test_local_authority_loads_only_the_committed_test_root() -> None:
    # Given: explicit local mode with no caller-selected trust material.
    # When: the local approval authority loads.
    authority = load_approval_authority(AuthorityMode.LOCAL)
    # Then: the committed test identity is the sole root.
    assert authority.descriptor.environment is Environment.TEST
    assert authority.descriptor.root_key_id.startswith("test-only-")


def test_production_authority_fails_when_root_secret_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a valid production descriptor with no root signing secret environment value.
    signing_key = SigningKey(b"\x11" * 32)
    descriptor = production_descriptor(signing_key)
    _trust_descriptor(monkeypatch, descriptor)
    monkeypatch.delenv("APPROVAL_ROOT_KEY_SECRET", raising=False)
    # When: production authority startup is attempted.
    with pytest.raises(AuthorityLoadError) as caught:
        _ = load_approval_authority(AuthorityMode.PRODUCTION, descriptor)
    # Then: startup fails with the stable missing-authority code.
    assert caught.value.code is AuthorityLoadErrorCode.ROOT_MATERIAL_MISSING


def test_production_authority_rejects_committed_test_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: test root material supplied under the production environment variable.
    local = load_approval_authority(AuthorityMode.LOCAL)
    fixture = Path(__file__).resolve().parents[1] / "fixtures/approval/TEST_ONLY_root_private.pem"
    monkeypatch.setenv("APPROVAL_ROOT_KEY_SECRET", fixture.read_text(encoding="utf-8"))
    # When: production startup receives the committed test descriptor.
    with pytest.raises(AuthorityLoadError) as caught:
        _ = load_approval_authority(AuthorityMode.PRODUCTION, local.descriptor)
    # Then: test trust is rejected before any session key can be issued.
    assert caught.value.code is AuthorityLoadErrorCode.TEST_ROOT_FORBIDDEN


def test_production_authority_accepts_matching_non_test_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a production descriptor whose Ed25519 key matches the distinct secret.
    signing_key = SigningKey(b"\x22" * 32)
    descriptor = production_descriptor(signing_key)
    _trust_descriptor(monkeypatch, descriptor)
    monkeypatch.setenv("APPROVAL_ROOT_KEY_SECRET", encode_base64url(bytes(signing_key)))
    # When: production authority startup validates the trust material.
    authority = load_approval_authority(AuthorityMode.PRODUCTION, descriptor)
    # Then: the exact descriptor is exposed without private material.
    assert authority.descriptor == descriptor
    assert "22" * 32 not in repr(authority)


def test_production_authority_rejects_test_public_fingerprint_after_repackaging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: the committed test key disguised with production ID, hash, and environment.
    fixture = Path(__file__).resolve().parents[1] / "fixtures/approval/TEST_ONLY_root_private.pem"
    test_key = parse_signing_key(fixture.read_text(encoding="utf-8"))
    descriptor = production_descriptor(test_key)
    monkeypatch.setenv("APPROVAL_ROOT_KEY_SECRET", fixture.read_text(encoding="utf-8"))
    # When: production startup validates the raw Ed25519 public fingerprint.
    with pytest.raises(AuthorityLoadError) as caught:
        _ = load_approval_authority(AuthorityMode.PRODUCTION, descriptor)
    # Then: repackaging cannot convert a test key into trusted production authority.
    assert caught.value.code is AuthorityLoadErrorCode.TEST_ROOT_FORBIDDEN


def test_production_authority_rejects_descriptor_secret_key_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a valid production descriptor and a different production-shaped secret.
    descriptor = production_descriptor(SigningKey(b"\x33" * 32))
    _trust_descriptor(monkeypatch, descriptor)
    monkeypatch.setenv(
        "APPROVAL_ROOT_KEY_SECRET",
        encode_base64url(bytes(SigningKey(b"\x44" * 32))),
    )
    # When: startup binds descriptor to signing material.
    with pytest.raises(AuthorityLoadError) as caught:
        _ = load_approval_authority(AuthorityMode.PRODUCTION, descriptor)
    # Then: no mismatched root can issue a certificate.
    assert caught.value.code is AuthorityLoadErrorCode.ROOT_KEY_MISMATCH


def test_root_certified_session_and_proof_verify_offline_with_exact_preimages() -> None:
    # Given: a local root, a 60-second session, and a bound approval request.
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
            nonce=b"\x00" * 16,
        )
    )
    # When: the session signs an approval proof.
    proof = session.issue_proof(
        ApprovalProofIssue(
            request=request,
            decision=ApprovalDecision.APPROVED,
            proof_id="approval-proof-0001",
            approved_at="2026-08-27T00:00:00Z",
        )
    )
    context = ApprovalValidationContext(
        root=authority.descriptor,
        certificate=session.certificate,
        request=request,
        environment=Environment.TEST,
        trusted_root_hashes=frozenset({authority.descriptor.descriptor_hash}),
        consumed_nonces=frozenset(),
        now=datetime(2026, 8, 27, 0, 0, 30, tzinfo=UTC),
    )
    # Then: the Task2 signing bytes, hashes, TTLs, and complete chain verify offline.
    validate_approval_chain(proof, context)
    _ = authority.descriptor.public_key_jwk.x
    assert len(certificate_signing_bytes(session.certificate)) > 32
    assert len(proof_signing_bytes(proof)) > 32
    assert certificate_hash(session.certificate) == proof.certificate_hash
    assert decode_base64url(session.certificate.certificate_signature)
    assert session.certificate.expires_at == "2026-08-27T00:01:00Z"
    assert proof.expires_at == "2026-08-27T00:01:00Z"


def test_session_authority_never_serializes_or_displays_private_key() -> None:
    # Given: one live session signing authority.
    session = load_approval_authority(AuthorityMode.CI).issue_session(
        SessionIssue(session_id="session-0001", issued_at="2026-08-27T00:00:00Z")
    )
    # When: public representations are inspected.
    public_text = repr(session)
    # Then: only the public certificate is representable.
    assert "SigningKey" not in public_text
    assert "private" not in public_text.lower()
