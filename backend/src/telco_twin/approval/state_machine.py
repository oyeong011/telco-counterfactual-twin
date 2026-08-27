"""Append-only evidence states with application-owned trust and time."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum, unique
from typing import TYPE_CHECKING, assert_never, final, override

import anyio

from telco_twin.domain.approval import (
    ApprovalDecision,
    ApprovalProof,
    ApprovalRequest,
    ApprovalValidationContext,
    SessionKeyCertificate,
    proof_hash,
    validate_approval_chain,
)
from telco_twin.safety.local_policy import (
    PolicyAdmission,
    PolicyDecision,
    PolicyDecisionRejected,
    PolicyEvaluation,
    revalidate_policy_decision,
)
from telco_twin.state.trusted_clock import TrustedClock, trusted_now

if TYPE_CHECKING:
    from telco_twin.approval.trust import ApprovalTrustConfig
    from telco_twin.domain._contract import ContractId, Sha256Hex


@unique
class ApprovalEvidenceState(StrEnum):
    """Only evidence states; none grants network authority."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


@unique
class ApprovalStateErrorCode(StrEnum):
    """Stable state admission and transition failures."""

    POLICY_INELIGIBLE = "policy-ineligible"
    EVIDENCE_BINDING_MISMATCH = "evidence-binding-mismatch"
    POLICY_PROVENANCE_REQUIRED = "policy-provenance-required"
    REQUEST_EXISTS = "approval-request-exists"
    REQUEST_UNKNOWN = "approval-request-unknown"
    REQUEST_CONTEXT_MISMATCH = "approval-request-context-mismatch"


@dataclass(frozen=True, slots=True)
class ApprovalStateError(Exception):
    """Typed evidence-state failure."""

    code: ApprovalStateErrorCode

    @override
    def __str__(self) -> str:
        return self.code.value


@dataclass(frozen=True, slots=True)
class ApprovalEvidenceRecord:
    """Immutable request state and optional complete proof identity."""

    request: ApprovalRequest
    state: ApprovalEvidenceState
    proof_hash: Sha256Hex | None


@final
class ApprovalStateMachine:
    """Evidence ledger that owns root trust, certificates, replay, and time."""

    def __init__(self, trust: ApprovalTrustConfig, clock: TrustedClock) -> None:
        """Capture immutable application trust and its time provider."""
        self._trust = trust
        self._clock = clock
        self._lock = anyio.Lock()
        self._records: dict[ContractId, ApprovalEvidenceRecord] = {}
        self._certificates: dict[ContractId, SessionKeyCertificate] = {}
        self._policies: dict[ContractId, PolicyDecision] = {}
        self._consumed_nonces: set[str] = set()

    async def record_request(
        self,
        request: ApprovalRequest,
        policy: PolicyAdmission,
        certificate: SessionKeyCertificate,
    ) -> ApprovalEvidenceRecord:
        """Admit pending state from internal policy and bound public certificate."""
        match policy:
            case PolicyEvaluation():
                raise ApprovalStateError(ApprovalStateErrorCode.POLICY_PROVENANCE_REQUIRED)
            case PolicyDecision():
                verification = revalidate_policy_decision(policy, self._clock)
            case _:  # pragma: no cover - exhaustive typed union
                assert_never(policy)
        match verification:
            case PolicyDecisionRejected():
                raise ApprovalStateError(ApprovalStateErrorCode.POLICY_PROVENANCE_REQUIRED)
            case PolicyEvaluation():
                evidence = verification
            case _:  # pragma: no cover - exhaustive typed union
                assert_never(verification)
        if not evidence.eligible:
            raise ApprovalStateError(ApprovalStateErrorCode.POLICY_INELIGIBLE)
        bindings_match = (
            request.patch_hash == evidence.patch_hash
            and request.simulation_hash == evidence.simulation_hash
            and request.policy_hash == evidence.policy_hash
            and certificate.session_id == request.session_id
            and certificate.root_key_id == self._trust.root.root_key_id
            and certificate.environment is self._trust.environment
        )
        if not bindings_match:
            raise ApprovalStateError(ApprovalStateErrorCode.EVIDENCE_BINDING_MISMATCH)
        async with self._lock:
            if request.request_id in self._records:
                raise ApprovalStateError(ApprovalStateErrorCode.REQUEST_EXISTS)
            record = ApprovalEvidenceRecord(
                request=request,
                state=ApprovalEvidenceState.PENDING,
                proof_hash=None,
            )
            self._records[request.request_id] = record
            self._certificates[request.request_id] = certificate
            self._policies[request.request_id] = policy
            return record

    async def record_proof(self, proof: ApprovalProof) -> ApprovalEvidenceRecord:
        """Validate against stored request/certificate and append terminal evidence."""
        async with self._lock:
            record = self._records.get(proof.approval_request_id)
            if record is None:
                raise ApprovalStateError(ApprovalStateErrorCode.REQUEST_UNKNOWN)
            certificate = self._certificates[record.request.request_id]
            context = ApprovalValidationContext(
                root=self._trust.root,
                certificate=certificate,
                request=record.request,
                environment=self._trust.environment,
                trusted_root_hashes=self._trust.trusted_root_hashes,
                consumed_nonces=frozenset(self._consumed_nonces),
                now=trusted_now(self._clock),
            )
            validate_approval_chain(proof, context)
            policy = self._policies[record.request.request_id]
            verification = revalidate_policy_decision(policy, self._clock)
            match verification:
                case PolicyDecisionRejected():
                    raise ApprovalStateError(ApprovalStateErrorCode.POLICY_PROVENANCE_REQUIRED)
                case PolicyEvaluation():
                    pass
                case _:  # pragma: no cover - exhaustive typed union
                    assert_never(verification)
            match proof.decision:
                case ApprovalDecision.APPROVED:
                    state = ApprovalEvidenceState.APPROVED
                case ApprovalDecision.REJECTED:
                    state = ApprovalEvidenceState.REJECTED
                case _:  # pragma: no cover - exhaustive enum
                    assert_never(proof.decision)
            updated = ApprovalEvidenceRecord(
                request=record.request,
                state=state,
                proof_hash=proof_hash(proof),
            )
            self._consumed_nonces.add(proof.nonce)
            self._records[record.request.request_id] = updated
            return updated

    async def get(self, request_id: ContractId) -> ApprovalEvidenceRecord | None:
        """Read one immutable evidence record without exposing ledger aliases."""
        async with self._lock:
            return self._records.get(request_id)
