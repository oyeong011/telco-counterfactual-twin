"""Environment-bound root authority and short-lived session signers."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum, unique
from pathlib import Path
from typing import Final, assert_never, final, override

from nacl.signing import SigningKey

from telco_twin.approval.crypto import (
    SigningMaterialError,
    parse_signing_key,
    sign_certificate,
    sign_proof,
)
from telco_twin.domain._contract import (
    ContractId,
    Sha256Hex,
    StrictContract,
    UtcTimestamp,
    utc_datetime,
)
from telco_twin.domain.approval import (
    ApprovalDecision,
    ApprovalProof,
    ApprovalRequest,
    ContractErrorCode,
    ContractViolationError,
    Ed25519Jwk,
    Environment,
    RootDescriptor,
    SessionKeyCertificate,
    certificate_hash,
    encode_base64url,
    validate_root_trust,
)

TEST_FIXTURES: Final = Path(__file__).resolve().parents[3] / "tests/fixtures/approval"
SIGNATURE_PLACEHOLDER: Final = encode_base64url(b"\0" * 64)
NONCE_BYTES: Final = 16


@unique
class AuthorityMode(StrEnum):
    """Closed startup trust modes."""

    LOCAL = "local"
    CI = "ci"
    PRODUCTION = "production"


@unique
class AuthorityLoadErrorCode(StrEnum):
    """Stable startup failures for root authority configuration."""

    ROOT_DESCRIPTOR_MISSING = "root-descriptor-missing"
    ROOT_MATERIAL_MISSING = "root-material-missing"
    ROOT_MATERIAL_INVALID = "root-material-invalid"
    ROOT_KEY_MISMATCH = "root-key-mismatch"
    TEST_ROOT_FORBIDDEN = "test-root-forbidden"
    ROOT_UNTRUSTED = "root-untrusted"
    SESSION_OUTSIDE_ROOT_WINDOW = "session-outside-root-window"
    REQUEST_NONCE_INVALID = "request-nonce-invalid"
    PROOF_OUTSIDE_EVIDENCE_WINDOW = "proof-outside-evidence-window"


@dataclass(frozen=True, slots=True)
class AuthorityLoadError(Exception):
    """Typed authority startup or issuance failure."""

    code: AuthorityLoadErrorCode

    @override
    def __str__(self) -> str:
        return self.code.value


@dataclass(frozen=True, slots=True)
class SessionIssue:
    """Inputs for one exact 60-second root-certified session."""

    session_id: ContractId
    issued_at: UtcTimestamp


@dataclass(frozen=True, slots=True)
class ApprovalRequestIssue:
    """Complete request bindings with caller-supplied deterministic nonce bytes."""

    request_id: ContractId
    session_id: ContractId
    patch_hash: Sha256Hex
    simulation_hash: Sha256Hex
    policy_hash: Sha256Hex
    requested_at: UtcTimestamp
    nonce: bytes


@dataclass(frozen=True, slots=True)
class ApprovalProofIssue:
    """Evidence decision bound to an existing pending request."""

    request: ApprovalRequest
    decision: ApprovalDecision
    proof_id: ContractId
    approved_at: UtcTimestamp


class _AuthoritySelection(StrictContract):
    mode: AuthorityMode


def _timestamp_plus_sixty(value: UtcTimestamp) -> UtcTimestamp:
    return (utc_datetime(value) + timedelta(seconds=60)).strftime("%Y-%m-%dT%H:%M:%SZ")


@final
class SessionApprovalAuthority:
    """Short-lived session signer whose private key is never representable."""

    __slots__ = ("__signing_key", "_certificate")

    def __init__(self, certificate: SessionKeyCertificate, signing_key: SigningKey) -> None:
        """Retain only private signing state and its public certificate."""
        self._certificate = certificate
        self.__signing_key = signing_key

    @property
    def certificate(self) -> SessionKeyCertificate:
        """Expose only the root-certified public session key."""
        return self._certificate

    def issue_proof(self, issue: ApprovalProofIssue) -> ApprovalProof:
        """Create an exact 60-second evidence proof within request/session windows."""
        expires_at = _timestamp_plus_sixty(issue.approved_at)
        if (
            issue.request.session_id != self._certificate.session_id
            or expires_at > issue.request.expires_at
            or expires_at > self._certificate.expires_at
        ):
            raise AuthorityLoadError(AuthorityLoadErrorCode.PROOF_OUTSIDE_EVIDENCE_WINDOW)
        draft = ApprovalProof(
            proof_id=issue.proof_id,
            approval_request_id=issue.request.request_id,
            session_id=issue.request.session_id,
            session_key_id=self._certificate.session_key_id,
            patch_hash=issue.request.patch_hash,
            simulation_hash=issue.request.simulation_hash,
            policy_hash=issue.request.policy_hash,
            nonce=issue.request.nonce,
            decision=issue.decision,
            approved_at=issue.approved_at,
            expires_at=expires_at,
            certificate_hash=certificate_hash(self._certificate),
            proof_signature=SIGNATURE_PLACEHOLDER,
            schema_version="1.0",
        )
        return sign_proof(self.__signing_key, draft)

    @override
    def __repr__(self) -> str:
        return f"SessionApprovalAuthority(certificate={self._certificate!r})"


@final
class RootApprovalAuthority:
    """Environment-validated root signer with public-descriptor-only representation."""

    __slots__ = ("__signing_key", "_descriptor")

    def __init__(self, descriptor: RootDescriptor, signing_key: SigningKey) -> None:
        """Retain only private signing state and its public descriptor."""
        self._descriptor = descriptor
        self.__signing_key = signing_key

    @property
    def descriptor(self) -> RootDescriptor:
        """Expose the trusted public root descriptor."""
        return self._descriptor

    def issue_session(self, issue: SessionIssue) -> SessionApprovalAuthority:
        """Issue a fresh root-certified Ed25519 session key for exactly 60 seconds."""
        expires_at = _timestamp_plus_sixty(issue.issued_at)
        if issue.issued_at < self._descriptor.not_before or expires_at > self._descriptor.not_after:
            raise AuthorityLoadError(AuthorityLoadErrorCode.SESSION_OUTSIDE_ROOT_WINDOW)
        session_key = SigningKey.generate()
        prefix = (
            "test-only-session" if self._descriptor.environment is Environment.TEST else "session"
        )
        key_digest = hashlib.sha256(bytes(session_key.verify_key)).hexdigest()[:20]
        draft = SessionKeyCertificate(
            session_id=issue.session_id,
            session_key_id=f"{prefix}-{key_digest}",
            session_public_key_jwk=Ed25519Jwk(
                kty="OKP",
                crv="Ed25519",
                x=encode_base64url(bytes(session_key.verify_key)),
            ),
            root_key_id=self._descriptor.root_key_id,
            issued_at=issue.issued_at,
            expires_at=expires_at,
            environment=self._descriptor.environment,
            certificate_signature=SIGNATURE_PLACEHOLDER,
            schema_version="1.0",
        )
        return SessionApprovalAuthority(sign_certificate(self.__signing_key, draft), session_key)

    @override
    def __repr__(self) -> str:
        return f"RootApprovalAuthority(descriptor={self._descriptor!r})"


def issue_approval_request(issue: ApprovalRequestIssue) -> ApprovalRequest:
    """Create a pending exact-60-second request bound to all evidence hashes."""
    if len(issue.nonce) != NONCE_BYTES:
        raise AuthorityLoadError(AuthorityLoadErrorCode.REQUEST_NONCE_INVALID)
    return ApprovalRequest(
        request_id=issue.request_id,
        session_id=issue.session_id,
        patch_hash=issue.patch_hash,
        simulation_hash=issue.simulation_hash,
        policy_hash=issue.policy_hash,
        nonce=encode_base64url(issue.nonce),
        requested_at=issue.requested_at,
        expires_at=_timestamp_plus_sixty(issue.requested_at),
        state="pending",
        schema_version="1.0",
    )


def _local_authority() -> RootApprovalAuthority:
    descriptor = RootDescriptor.model_validate_json(
        (TEST_FIXTURES / "test-root-descriptor.json").read_bytes()
    )
    key = parse_signing_key((TEST_FIXTURES / "TEST_ONLY_root_private.pem").read_text())
    return RootApprovalAuthority(descriptor, key)


def _production_authority(descriptor: RootDescriptor | None) -> RootApprovalAuthority:
    if descriptor is None:
        raise AuthorityLoadError(AuthorityLoadErrorCode.ROOT_DESCRIPTOR_MISSING)
    try:
        validate_root_trust(
            descriptor,
            Environment.PRODUCTION,
            frozenset({descriptor.descriptor_hash}),
        )
    except ContractViolationError as error:
        code = (
            AuthorityLoadErrorCode.TEST_ROOT_FORBIDDEN
            if error.code is ContractErrorCode.TEST_ROOT_FORBIDDEN
            else AuthorityLoadErrorCode.ROOT_UNTRUSTED
        )
        raise AuthorityLoadError(code) from error
    encoded = os.getenv("APPROVAL_ROOT_KEY_SECRET")
    if encoded is None:
        raise AuthorityLoadError(AuthorityLoadErrorCode.ROOT_MATERIAL_MISSING)
    try:
        key = parse_signing_key(encoded)
    except SigningMaterialError as error:
        raise AuthorityLoadError(AuthorityLoadErrorCode.ROOT_MATERIAL_INVALID) from error
    if encode_base64url(bytes(key.verify_key)) != descriptor.public_key_jwk.x:
        raise AuthorityLoadError(AuthorityLoadErrorCode.ROOT_KEY_MISMATCH)
    return RootApprovalAuthority(descriptor, key)


def load_approval_authority(
    mode: AuthorityMode,
    descriptor: RootDescriptor | None = None,
) -> RootApprovalAuthority:
    """Load fixed test trust locally/CI or validated external production trust."""
    selection = _AuthoritySelection(mode=mode)
    match selection.mode:
        case AuthorityMode.LOCAL | AuthorityMode.CI:
            return _local_authority()
        case AuthorityMode.PRODUCTION:
            return _production_authority(descriptor)
        case _:
            assert_never(selection.mode)
