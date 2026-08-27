"""Exact approval hash preimages and Ed25519 chain verification."""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from typing import Final

from nacl.exceptions import BadSignatureError
from nacl.signing import VerifyKey

from ._approval_models import (
    ApprovalProof,
    ApprovalValidationContext,
    ContractErrorCode,
    ContractViolationError,
    Environment,
    RootDescriptor,
    SessionKeyCertificate,
    decode_base64url,
)
from ._contract import utc_datetime
from .canonical import canonical_model_bytes

CERTIFICATE_DOMAIN: Final = b"telco-twin/session-cert/v1\0"
PROOF_DOMAIN: Final = b"telco-twin/approval-proof/v1\0"
TEST_ONLY_ROOT_HASHES: Final[frozenset[str]] = frozenset(
    {"0a0ac92bec879131e15c2b22d6fdeff8f88b7e6e753dcaa8f23568fe9e0300c9"}
)
TEST_ONLY_PUBLIC_KEY_FINGERPRINTS: Final[frozenset[str]] = frozenset(
    {"21fe31dfa154a261626bf854046fd2271b7bed4b6abe45aa58877ef47f9721b9"}
)
PRODUCTION_ENVIRONMENTS: Final[frozenset[Environment]] = frozenset({Environment.PRODUCTION})


@dataclass(frozen=True, slots=True)
class _SignatureClaim:
    message: bytes
    signature: str
    public_x: str
    error_code: ContractErrorCode


def descriptor_hash(root: RootDescriptor) -> str:
    """Hash the descriptor without its descriptor_hash field."""
    return hashlib.sha256(
        canonical_model_bytes(root, exclude=frozenset({"descriptor_hash"}))
    ).hexdigest()


def certificate_signing_bytes(certificate: SessionKeyCertificate) -> bytes:
    """Return the exact root-signature preimage."""
    return CERTIFICATE_DOMAIN + canonical_model_bytes(
        certificate, exclude=frozenset({"certificate_signature"})
    )


def certificate_hash(certificate: SessionKeyCertificate) -> str:
    """Hash the complete signed session certificate."""
    return hashlib.sha256(canonical_model_bytes(certificate)).hexdigest()


def proof_signing_bytes(proof: ApprovalProof) -> bytes:
    """Return the exact session-signature preimage."""
    return PROOF_DOMAIN + canonical_model_bytes(proof, exclude=frozenset({"proof_signature"}))


def proof_hash(proof: ApprovalProof) -> str:
    """Hash the complete signed proof without embedding that hash."""
    return hashlib.sha256(canonical_model_bytes(proof)).hexdigest()


def _verify_signature(claim: _SignatureClaim) -> None:
    try:
        _ = VerifyKey(decode_base64url(claim.public_x)).verify(
            claim.message, decode_base64url(claim.signature)
        )
    except BadSignatureError as error:
        raise ContractViolationError(claim.error_code) from error


def validate_root_trust(
    root: RootDescriptor, environment: Environment, trusted_root_hashes: frozenset[str]
) -> None:
    """Verify descriptor integrity and environment-specific trust."""
    if descriptor_hash(root) != root.descriptor_hash:
        raise ContractViolationError(ContractErrorCode.ROOT_HASH_MISMATCH)
    if environment in PRODUCTION_ENVIRONMENTS:
        public_key_fingerprint = hashlib.sha256(decode_base64url(root.public_key_jwk.x)).hexdigest()
        is_test_root = (
            root.environment is Environment.TEST
            or root.root_key_id.startswith("test-only-")
            or root.descriptor_hash in TEST_ONLY_ROOT_HASHES
            or public_key_fingerprint in TEST_ONLY_PUBLIC_KEY_FINGERPRINTS
        )
        if is_test_root:
            raise ContractViolationError(ContractErrorCode.TEST_ROOT_FORBIDDEN)
    if root.environment is not environment or root.descriptor_hash not in trusted_root_hashes:
        raise ContractViolationError(ContractErrorCode.ROOT_UNTRUSTED)


def _validate_trust_time(
    proof: ApprovalProof,
    context: ApprovalValidationContext,
) -> None:
    root_start = utc_datetime(context.root.not_before)
    root_end = utc_datetime(context.root.not_after)
    if context.now < root_start:
        raise ContractViolationError(ContractErrorCode.ROOT_NOT_YET_VALID)
    if context.now >= root_end:
        raise ContractViolationError(ContractErrorCode.ROOT_EXPIRED)
    certificate = context.certificate
    certificate_issued_at = utc_datetime(certificate.issued_at)
    certificate_expires_at = utc_datetime(certificate.expires_at)
    if certificate_issued_at < root_start or certificate_expires_at > root_end:
        raise ContractViolationError(ContractErrorCode.CERTIFICATE_OUTSIDE_ROOT_WINDOW)
    approved_at = utc_datetime(proof.approved_at)
    proof_expires_at = utc_datetime(proof.expires_at)
    if context.now < approved_at:
        raise ContractViolationError(ContractErrorCode.APPROVAL_NOT_YET_VALID)
    if context.now < certificate_issued_at:
        raise ContractViolationError(ContractErrorCode.CERTIFICATE_NOT_YET_VALID)
    if context.now >= proof_expires_at:
        raise ContractViolationError(ContractErrorCode.APPROVAL_EXPIRED)
    if context.now >= certificate_expires_at:
        raise ContractViolationError(ContractErrorCode.CERTIFICATE_EXPIRED)
    if approved_at < certificate_issued_at:
        raise ContractViolationError(ContractErrorCode.PROOF_BEFORE_CERTIFICATE)
    if proof_expires_at > certificate_expires_at:
        raise ContractViolationError(ContractErrorCode.PROOF_AFTER_CERTIFICATE)


def _validate_certificate(context: ApprovalValidationContext) -> None:
    certificate = context.certificate
    if (
        certificate.root_key_id != context.root.root_key_id
        or certificate.environment is not context.environment
        or certificate.session_id != context.request.session_id
    ):
        raise ContractViolationError(ContractErrorCode.CERTIFICATE_BINDING_MISMATCH)
    _verify_signature(
        _SignatureClaim(
            message=certificate_signing_bytes(certificate),
            signature=certificate.certificate_signature,
            public_x=context.root.public_key_jwk.x,
            error_code=ContractErrorCode.CERTIFICATE_SIGNATURE_INVALID,
        )
    )


def validate_approval_chain(proof: ApprovalProof, context: ApprovalValidationContext) -> None:
    """Validate root, certificate, request binding, signature, time, and replay state."""
    validate_root_trust(context.root, context.environment, context.trusted_root_hashes)
    _validate_trust_time(proof, context)
    _validate_certificate(context)
    request = context.request
    certificate = context.certificate
    if certificate_hash(certificate) != proof.certificate_hash:
        raise ContractViolationError(ContractErrorCode.CERTIFICATE_HASH_MISMATCH)
    bindings_match = (
        proof.approval_request_id == request.request_id
        and proof.session_id == request.session_id == certificate.session_id
        and proof.session_key_id == certificate.session_key_id
        and proof.patch_hash == request.patch_hash
        and proof.simulation_hash == request.simulation_hash
        and proof.policy_hash == request.policy_hash
        and proof.nonce == request.nonce
        and utc_datetime(proof.approved_at) >= utc_datetime(request.requested_at)
        and utc_datetime(proof.expires_at) <= utc_datetime(request.expires_at)
    )
    if not bindings_match:
        raise ContractViolationError(ContractErrorCode.APPROVAL_BINDING_MISMATCH)
    if proof.nonce in context.consumed_nonces:
        raise ContractViolationError(ContractErrorCode.NONCE_REPLAYED)
    _verify_signature(
        _SignatureClaim(
            message=proof_signing_bytes(proof),
            signature=proof.proof_signature,
            public_x=certificate.session_public_key_jwk.x,
            error_code=ContractErrorCode.PROOF_SIGNATURE_INVALID,
        )
    )


def encode_base64url(value: bytes) -> str:
    """Encode canonical base64url without padding."""
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")
