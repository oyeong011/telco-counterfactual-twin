"""Private Ed25519 parsing and exact Task2 signing operations."""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from enum import StrEnum, unique
from typing import Final, override

from nacl.signing import SigningKey

from telco_twin.domain.approval import (
    ApprovalProof,
    SessionKeyCertificate,
    certificate_signing_bytes,
    encode_base64url,
    proof_signing_bytes,
)

PKCS8_ED25519_PREFIX: Final = bytes.fromhex("302e020100300506032b657004220420")
ED25519_SEED_BYTES: Final = 32


@unique
class SigningMaterialErrorCode(StrEnum):
    """Stable private-key parsing failures."""

    PEM = "root-material-pem"
    ALGORITHM = "root-material-algorithm"
    BASE64URL = "root-material-base64url"
    LENGTH = "root-material-length"


@dataclass(frozen=True, slots=True)
class SigningMaterialError(Exception):
    """Root signing material is malformed or does not encode an Ed25519 seed."""

    code: SigningMaterialErrorCode

    @override
    def __str__(self) -> str:
        return self.code.value


def parse_signing_key(encoded: str) -> SigningKey:
    """Parse a raw base64url seed or strict PKCS#8 Ed25519 PEM."""
    stripped = encoded.strip()
    if stripped.startswith("-----BEGIN PRIVATE KEY-----"):
        lines = stripped.splitlines()
        if lines[-1] != "-----END PRIVATE KEY-----":
            raise SigningMaterialError(SigningMaterialErrorCode.PEM)
        try:
            decoded = base64.b64decode("".join(lines[1:-1]), validate=True)
        except (binascii.Error, ValueError) as error:
            raise SigningMaterialError(SigningMaterialErrorCode.PEM) from error
        if not decoded.startswith(PKCS8_ED25519_PREFIX):
            raise SigningMaterialError(SigningMaterialErrorCode.ALGORITHM)
        seed = decoded[len(PKCS8_ED25519_PREFIX) :]
    else:
        if "=" in stripped:
            raise SigningMaterialError(SigningMaterialErrorCode.BASE64URL)
        try:
            seed = base64.urlsafe_b64decode(stripped + ("=" * (-len(stripped) % 4)))
        except (binascii.Error, ValueError) as error:
            raise SigningMaterialError(SigningMaterialErrorCode.BASE64URL) from error
        if base64.urlsafe_b64encode(seed).rstrip(b"=").decode("ascii") != stripped:
            raise SigningMaterialError(SigningMaterialErrorCode.BASE64URL)
    if len(seed) != ED25519_SEED_BYTES:
        raise SigningMaterialError(SigningMaterialErrorCode.LENGTH)
    return SigningKey(seed)


def sign_certificate(
    signing_key: SigningKey,
    certificate: SessionKeyCertificate,
) -> SessionKeyCertificate:
    """Sign the exact root certificate preimage from the Task2 contract."""
    signature = signing_key.sign(certificate_signing_bytes(certificate)).signature
    return certificate.model_copy(update={"certificate_signature": encode_base64url(signature)})


def sign_proof(signing_key: SigningKey, proof: ApprovalProof) -> ApprovalProof:
    """Sign the exact session proof preimage from the Task2 contract."""
    signature = signing_key.sign(proof_signing_bytes(proof)).signature
    return proof.model_copy(update={"proof_signature": encode_base64url(signature)})
