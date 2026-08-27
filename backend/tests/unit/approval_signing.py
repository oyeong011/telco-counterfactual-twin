"""Test-only signing helpers for complete approval-chain regressions."""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Final

import rfc8785
from nacl.signing import SigningKey
from pydantic import JsonValue, TypeAdapter

from telco_twin.domain.approval import (
    ApprovalProof,
    ApprovalValidationContext,
    Environment,
    RootDescriptor,
    SessionKeyCertificate,
    certificate_hash,
    certificate_signing_bytes,
    encode_base64url,
    proof_signing_bytes,
)

from .contract_cases import APPROVAL_FIXTURES, approval_context, load_approval_bundle
from .contract_payloads import JsonObject

JSON_OBJECT_ADAPTER: Final[TypeAdapter[JsonObject]] = TypeAdapter(JsonObject)
PRIVATE_KEY_HEADER_BYTES: Final = 16
SESSION_SEED_LABEL: Final = b"telco-twin/test-session/v1"


@dataclass(frozen=True, slots=True)
class SignedApprovalChain:
    proof: ApprovalProof
    context: ApprovalValidationContext


@dataclass(frozen=True, slots=True)
class ApprovalTimes:
    certificate_issued_at: datetime
    proof_approved_at: datetime
    now: datetime


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _root_signing_key() -> SigningKey:
    lines = (APPROVAL_FIXTURES / "TEST_ONLY_root_private.pem").read_text().splitlines()
    der = base64.b64decode("".join(lines[1:-1]), validate=True)
    return SigningKey(der[PRIVATE_KEY_HEADER_BYTES:])


def _session_signing_key() -> SigningKey:
    return SigningKey(hashlib.sha256(SESSION_SEED_LABEL).digest())


def _sign_certificate(certificate: SessionKeyCertificate) -> SessionKeyCertificate:
    signature = _root_signing_key().sign(certificate_signing_bytes(certificate)).signature
    return certificate.model_copy(update={"certificate_signature": encode_base64url(signature)})


def _sign_proof(
    proof: ApprovalProof,
    certificate: SessionKeyCertificate,
) -> ApprovalProof:
    bound = proof.model_copy(update={"certificate_hash": certificate_hash(certificate)})
    signature = _session_signing_key().sign(proof_signing_bytes(bound)).signature
    return bound.model_copy(update={"proof_signature": encode_base64url(signature)})


def repackaged_production_chain() -> SignedApprovalChain:
    bundle = load_approval_bundle()
    payload = JSON_OBJECT_ADAPTER.validate_json(bundle.root.model_dump_json())
    payload["root_key_id"] = "production-root-0001"
    payload["environment"] = "production"
    unsigned: dict[str, JsonValue] = dict(payload)
    _ = unsigned.pop("descriptor_hash")
    payload["descriptor_hash"] = hashlib.sha256(rfc8785.dumps(unsigned)).hexdigest()
    root = RootDescriptor.model_validate(payload)
    certificate = _sign_certificate(
        bundle.certificate.model_copy(
            update={
                "root_key_id": root.root_key_id,
                "environment": Environment.PRODUCTION,
            }
        )
    )
    proof = _sign_proof(bundle.proof, certificate)
    context = replace(
        approval_context(),
        root=root,
        certificate=certificate,
        environment=Environment.PRODUCTION,
        trusted_root_hashes=frozenset({root.descriptor_hash}),
    )
    return SignedApprovalChain(proof, context)


def signed_temporal_chain(times: ApprovalTimes) -> SignedApprovalChain:
    bundle = load_approval_bundle()
    certificate_expires = times.certificate_issued_at + timedelta(seconds=60)
    proof_expires = times.proof_approved_at + timedelta(seconds=60)
    certificate = _sign_certificate(
        bundle.certificate.model_copy(
            update={
                "issued_at": _timestamp(times.certificate_issued_at),
                "expires_at": _timestamp(certificate_expires),
            }
        )
    )
    request = bundle.request.model_copy(
        update={
            "requested_at": _timestamp(times.proof_approved_at),
            "expires_at": _timestamp(proof_expires),
        }
    )
    proof = _sign_proof(
        bundle.proof.model_copy(
            update={
                "approved_at": _timestamp(times.proof_approved_at),
                "expires_at": _timestamp(proof_expires),
            }
        ),
        certificate,
    )
    context = replace(
        approval_context(),
        certificate=certificate,
        request=request,
        now=times.now,
    )
    return SignedApprovalChain(proof, context)
