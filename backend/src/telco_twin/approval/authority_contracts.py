"""Typed approval-authority configuration and issuance inputs."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum, unique
from typing import TYPE_CHECKING, override

if TYPE_CHECKING:
    from telco_twin.domain._contract import ContractId, Sha256Hex, UtcTimestamp
    from telco_twin.domain.approval import ApprovalDecision, ApprovalRequest


@unique
class AuthorityMode(StrEnum):
    """Closed startup trust modes."""

    LOCAL = "local"
    CI = "ci"
    PRODUCTION = "production"


@unique
class AuthorityLoadErrorCode(StrEnum):
    """Stable startup and issuance failures."""

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
    """Complete request bindings with deterministic nonce bytes."""

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
