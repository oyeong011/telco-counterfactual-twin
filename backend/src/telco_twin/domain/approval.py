"""Public approval-contract facade."""

from ._approval_crypto import (
    certificate_hash,
    certificate_signing_bytes,
    descriptor_hash,
    encode_base64url,
    proof_hash,
    proof_signing_bytes,
    validate_approval_chain,
    validate_root_trust,
)
from ._approval_models import (
    ApprovalDecision,
    ApprovalProof,
    ApprovalRequest,
    ApprovalValidationContext,
    ContractErrorCode,
    ContractViolationError,
    Ed25519Jwk,
    Environment,
    RootDescriptor,
    SessionKeyCertificate,
    decode_base64url,
)
from .canonical import canonical_json_bytes, canonical_model_bytes

__all__ = [
    "ApprovalDecision",
    "ApprovalProof",
    "ApprovalRequest",
    "ApprovalValidationContext",
    "ContractErrorCode",
    "ContractViolationError",
    "Ed25519Jwk",
    "Environment",
    "RootDescriptor",
    "SessionKeyCertificate",
    "canonical_json_bytes",
    "canonical_model_bytes",
    "certificate_hash",
    "certificate_signing_bytes",
    "decode_base64url",
    "descriptor_hash",
    "encode_base64url",
    "proof_hash",
    "proof_signing_bytes",
    "validate_approval_chain",
    "validate_root_trust",
]
