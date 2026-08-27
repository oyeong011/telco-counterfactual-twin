"""Closed approval request, root, certificate, and proof models."""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
from dataclasses import dataclass
from enum import StrEnum, unique
from typing import TYPE_CHECKING, Annotated, Final, Literal, Self, override

from pydantic import AfterValidator, WithJsonSchema, model_validator

from ._contract import (
    ContractId,
    SchemaVersion,
    Sha256Hex,
    StrictContract,
    UtcTimestamp,
    fail_validation,
    utc_datetime,
)
from .canonical import canonical_model_bytes

if TYPE_CHECKING:
    from datetime import datetime

BASE64URL_PATTERN: Final = re.compile(r"^[A-Za-z0-9_-]+$")
ED25519_PUBLIC_BYTES: Final = 32
ED25519_SIGNATURE_BYTES: Final = 64
NONCE_BYTES: Final = 16
TTL_SECONDS: Final = 60
JWK_COORDINATE_CHARS: Final = 43
SIGNATURE_CHARS: Final = 86
NONCE_CHARS: Final = 22
JWK_COORDINATE_PATTERN: Final = r"^[A-Za-z0-9_-]{43}$"
SIGNATURE_PATTERN: Final = r"^[A-Za-z0-9_-]{86}$"
NONCE_PATTERN: Final = r"^[A-Za-z0-9_-]{22}$"


@unique
class Environment(StrEnum):
    """Trust environment encoded into every approval key object."""

    TEST = "test"
    PRODUCTION = "production"


@unique
class ApprovalDecision(StrEnum):
    """The only evidence decisions in v0.1."""

    APPROVED = "approved"
    REJECTED = "rejected"


@unique
class ContractErrorCode(StrEnum):
    """Stable approval-chain failure codes."""

    ROOT_HASH_MISMATCH = "root-hash-mismatch"
    ROOT_UNTRUSTED = "root-untrusted"
    ROOT_NOT_YET_VALID = "root-not-yet-valid"
    ROOT_EXPIRED = "root-expired"
    TEST_ROOT_FORBIDDEN = "test-root-forbidden"
    CERTIFICATE_BINDING_MISMATCH = "certificate-binding-mismatch"
    CERTIFICATE_OUTSIDE_ROOT_WINDOW = "certificate-outside-root-window"
    CERTIFICATE_SIGNATURE_INVALID = "certificate-signature-invalid"
    CERTIFICATE_EXPIRED = "certificate-expired"
    CERTIFICATE_NOT_YET_VALID = "certificate-not-yet-valid"
    CERTIFICATE_HASH_MISMATCH = "certificate-hash-mismatch"
    APPROVAL_BINDING_MISMATCH = "approval-binding-mismatch"
    PROOF_BEFORE_CERTIFICATE = "proof_before_certificate"
    PROOF_AFTER_CERTIFICATE = "proof_after_certificate"
    PROOF_SIGNATURE_INVALID = "approval-signature-invalid"
    APPROVAL_EXPIRED = "approval-expired"
    APPROVAL_NOT_YET_VALID = "approval-not-yet-valid"
    NONCE_REPLAYED = "nonce-replayed"


@dataclass(frozen=True, slots=True)
class ContractViolationError(Exception):
    """Typed approval failure safe for a machine boundary."""

    code: ContractErrorCode

    @override
    def __str__(self) -> str:
        return self.code.value


def decode_base64url(value: str) -> bytes:
    """Decode canonical unpadded base64url or raise a stable Pydantic error."""
    if "=" in value or BASE64URL_PATTERN.fullmatch(value) is None:
        fail_validation("base64url_no_padding", "value must be unpadded canonical base64url")
    try:
        decoded = base64.urlsafe_b64decode(value + ("=" * (-len(value) % 4)))
    except (binascii.Error, ValueError):
        fail_validation("base64url_no_padding", "value must be unpadded canonical base64url")
    if base64.urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii") != value:
        fail_validation("base64url_no_padding", "value must be unpadded canonical base64url")
    return decoded


def _jwk_x(value: str) -> str:
    if len(decode_base64url(value)) != ED25519_PUBLIC_BYTES:
        fail_validation("ed25519_jwk", "Ed25519 JWK x must decode to 32 bytes")
    return value


def _signature(value: str) -> str:
    if len(decode_base64url(value)) != ED25519_SIGNATURE_BYTES:
        fail_validation("ed25519_signature", "Ed25519 signature must decode to 64 bytes")
    return value


def _nonce(value: str) -> str:
    if len(decode_base64url(value)) != NONCE_BYTES:
        fail_validation("nonce_128bit", "nonce must encode exactly 128 bits")
    return value


JwkX = Annotated[
    str,
    AfterValidator(_jwk_x),
    WithJsonSchema(
        {
            "type": "string",
            "minLength": JWK_COORDINATE_CHARS,
            "maxLength": JWK_COORDINATE_CHARS,
            "pattern": JWK_COORDINATE_PATTERN,
        }
    ),
]
Ed25519Signature = Annotated[
    str,
    AfterValidator(_signature),
    WithJsonSchema(
        {
            "type": "string",
            "minLength": SIGNATURE_CHARS,
            "maxLength": SIGNATURE_CHARS,
            "pattern": SIGNATURE_PATTERN,
        }
    ),
]
Nonce128 = Annotated[
    str,
    AfterValidator(_nonce),
    WithJsonSchema(
        {
            "type": "string",
            "minLength": NONCE_CHARS,
            "maxLength": NONCE_CHARS,
            "pattern": NONCE_PATTERN,
        }
    ),
]


class Ed25519Jwk(StrictContract):
    """Minimal public OKP JWK for Ed25519 verification."""

    kty: Literal["OKP"]
    crv: Literal["Ed25519"]
    x: JwkX


class ApprovalRequest(StrictContract):
    """Short-lived evidence-only approval request."""

    request_id: ContractId
    session_id: ContractId
    patch_hash: Sha256Hex
    simulation_hash: Sha256Hex
    policy_hash: Sha256Hex
    nonce: Nonce128
    requested_at: UtcTimestamp
    expires_at: UtcTimestamp
    state: Literal["pending"]
    schema_version: SchemaVersion

    @model_validator(mode="after")
    def ttl_is_exact(self) -> Self:
        """Require the exact v0.1 60-second request lifetime."""
        lifetime = utc_datetime(self.expires_at) - utc_datetime(self.requested_at)
        if lifetime.total_seconds() != TTL_SECONDS:
            fail_validation("ttl_60_seconds", "approval request TTL must be 60 seconds")
        return self


class RootDescriptor(StrictContract):
    """Self-hashed public approval-root descriptor."""

    root_key_id: ContractId
    algorithm: Literal["Ed25519"]
    public_key_jwk: Ed25519Jwk
    environment: Environment
    not_before: UtcTimestamp
    not_after: UtcTimestamp
    descriptor_hash: Sha256Hex
    schema_version: SchemaVersion

    @model_validator(mode="after")
    def hash_and_time_are_valid(self) -> Self:
        """Reject altered descriptors before trust lookup."""
        if utc_datetime(self.not_after) <= utc_datetime(self.not_before):
            fail_validation("root_time_order", "root validity window is empty")
        expected = hashlib.sha256(
            canonical_model_bytes(self, exclude=frozenset({"descriptor_hash"}))
        ).hexdigest()
        if self.descriptor_hash != expected:
            fail_validation("descriptor_hash_mismatch", "root descriptor hash mismatch")
        return self


class SessionKeyCertificate(StrictContract):
    """Root-certified, 60-second session verification key."""

    session_id: ContractId
    session_key_id: ContractId
    session_public_key_jwk: Ed25519Jwk
    root_key_id: ContractId
    issued_at: UtcTimestamp
    expires_at: UtcTimestamp
    environment: Environment
    certificate_signature: Ed25519Signature
    schema_version: SchemaVersion

    @model_validator(mode="after")
    def ttl_is_exact(self) -> Self:
        """Require the exact v0.1 60-second certificate lifetime."""
        lifetime = utc_datetime(self.expires_at) - utc_datetime(self.issued_at)
        if lifetime.total_seconds() != TTL_SECONDS:
            fail_validation("ttl_60_seconds", "session certificate TTL must be 60 seconds")
        return self


class ApprovalProof(StrictContract):
    """Session-signed decision bound to request, hashes, and nonce."""

    proof_id: ContractId
    approval_request_id: ContractId
    session_id: ContractId
    session_key_id: ContractId
    patch_hash: Sha256Hex
    simulation_hash: Sha256Hex
    policy_hash: Sha256Hex
    nonce: Nonce128
    decision: ApprovalDecision
    approved_at: UtcTimestamp
    expires_at: UtcTimestamp
    certificate_hash: Sha256Hex
    proof_signature: Ed25519Signature
    schema_version: SchemaVersion

    @model_validator(mode="after")
    def ttl_is_exact(self) -> Self:
        """Require the exact v0.1 60-second proof lifetime."""
        lifetime = utc_datetime(self.expires_at) - utc_datetime(self.approved_at)
        if lifetime.total_seconds() != TTL_SECONDS:
            fail_validation("ttl_60_seconds", "approval proof TTL must be 60 seconds")
        return self


@dataclass(frozen=True, slots=True)
class ApprovalValidationContext:
    """All immutable trust and replay facts needed to validate one proof."""

    root: RootDescriptor
    certificate: SessionKeyCertificate
    request: ApprovalRequest
    environment: Environment
    trusted_root_hashes: frozenset[str]
    consumed_nonces: frozenset[str]
    now: datetime
