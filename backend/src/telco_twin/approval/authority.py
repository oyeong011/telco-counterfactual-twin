"""Environment-bound root authority and short-lived session signers."""

from __future__ import annotations

import hashlib
from datetime import timedelta
from typing import Final, final, override

from nacl.signing import SigningKey

from telco_twin.approval.authority_contracts import (
    ApprovalProofIssue,
    ApprovalRequestIssue,
    AuthorityLoadError,
    AuthorityLoadErrorCode,
    AuthorityMode,
    SessionIssue,
)
from telco_twin.approval.crypto import sign_certificate, sign_proof
from telco_twin.approval.root_loader import load_root_authority_material
from telco_twin.domain._contract import UtcTimestamp, utc_datetime
from telco_twin.domain.approval import (
    ApprovalProof,
    ApprovalRequest,
    Ed25519Jwk,
    Environment,
    RootDescriptor,
    SessionKeyCertificate,
    certificate_hash,
    encode_base64url,
)

SIGNATURE_PLACEHOLDER: Final = encode_base64url(b"\0" * 64)
NONCE_BYTES: Final = 16

__all__ = (
    "ApprovalProofIssue",
    "ApprovalRequestIssue",
    "AuthorityLoadError",
    "AuthorityLoadErrorCode",
    "AuthorityMode",
    "RootApprovalAuthority",
    "SessionApprovalAuthority",
    "SessionIssue",
    "issue_approval_request",
    "load_approval_authority",
)


def _timestamp_plus_sixty(value: UtcTimestamp) -> UtcTimestamp:
    return (utc_datetime(value) + timedelta(seconds=60)).strftime("%Y-%m-%dT%H:%M:%SZ")


@final
class SessionApprovalAuthority:
    """Short-lived session signer whose private key is never representable."""

    __slots__ = ("__signing_key", "_certificate")

    def __init__(self, certificate: SessionKeyCertificate, signing_key: SigningKey) -> None:
        """Retain private session signing state and its public certificate."""
        self._certificate = certificate
        self.__signing_key = signing_key

    @property
    def certificate(self) -> SessionKeyCertificate:
        """Expose only the root-certified public session key."""
        return self._certificate

    def issue_proof(self, issue: ApprovalProofIssue) -> ApprovalProof:
        """Create an exact 60-second proof within request/session windows."""
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
    """Validated root signer with public-descriptor-only representation."""

    __slots__ = ("__signing_key", "_descriptor")

    def __init__(self, descriptor: RootDescriptor, signing_key: SigningKey) -> None:
        """Retain private root signing state and its public descriptor."""
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
        certificate = sign_certificate(self.__signing_key, draft)
        return SessionApprovalAuthority(certificate, session_key)

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


def load_approval_authority(
    mode: AuthorityMode,
    descriptor: RootDescriptor | None = None,
) -> RootApprovalAuthority:
    """Load fixed local/CI material or independently trusted production material."""
    material = load_root_authority_material(mode, descriptor)
    return RootApprovalAuthority(material.descriptor, material.signing_key)
