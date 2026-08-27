"""Append-only evidence states for policy-gated approval proofs."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum, unique
from typing import TYPE_CHECKING, assert_never, final, override

import anyio

from telco_twin.domain.approval import (
    ApprovalDecision,
    ApprovalProof,
    ApprovalRequest,
    ApprovalValidationContext,
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

if TYPE_CHECKING:
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
    """Append-only evidence ledger; revocation and network authority are unsupported."""

    def __init__(self) -> None:
        """Create an empty append-only evidence ledger."""
        self._lock = anyio.Lock()
        self._records: dict[ContractId, ApprovalEvidenceRecord] = {}
        self._policies: dict[ContractId, PolicyDecision] = {}
        self._consumed_nonces: set[str] = set()

    async def record_request(
        self,
        request: ApprovalRequest,
        policy: PolicyAdmission,
    ) -> ApprovalEvidenceRecord:
        """Admit pending state only after re-resolving internal policy provenance."""
        match policy:
            case PolicyEvaluation():
                raise ApprovalStateError(ApprovalStateErrorCode.POLICY_PROVENANCE_REQUIRED)
            case PolicyDecision():
                verification = revalidate_policy_decision(policy)
            case _:
                assert_never(policy)
        match verification:
            case PolicyDecisionRejected():
                raise ApprovalStateError(ApprovalStateErrorCode.POLICY_PROVENANCE_REQUIRED)
            case PolicyEvaluation():
                evidence = verification
            case _:
                assert_never(verification)
        if not evidence.eligible:
            raise ApprovalStateError(ApprovalStateErrorCode.POLICY_INELIGIBLE)
        if (
            request.patch_hash != evidence.patch_hash
            or request.simulation_hash != evidence.simulation_hash
            or request.policy_hash != evidence.policy_hash
        ):
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
            self._policies[request.request_id] = policy
            return record

    async def record_proof(
        self,
        proof: ApprovalProof,
        context: ApprovalValidationContext,
    ) -> ApprovalEvidenceRecord:
        """Validate and append one terminal approved/rejected evidence state."""
        async with self._lock:
            validation_context = replace(
                context,
                consumed_nonces=frozenset(self._consumed_nonces),
            )
            validate_approval_chain(proof, validation_context)
            record = self._records.get(proof.approval_request_id)
            if record is None:
                raise ApprovalStateError(ApprovalStateErrorCode.REQUEST_UNKNOWN)
            if record.request != context.request:
                raise ApprovalStateError(ApprovalStateErrorCode.REQUEST_CONTEXT_MISMATCH)
            policy = self._policies[record.request.request_id]
            verification = revalidate_policy_decision(policy)
            match verification:
                case PolicyDecisionRejected():
                    raise ApprovalStateError(ApprovalStateErrorCode.POLICY_PROVENANCE_REQUIRED)
                case PolicyEvaluation():
                    pass
                case _:
                    assert_never(verification)
            match proof.decision:
                case ApprovalDecision.APPROVED:
                    state = ApprovalEvidenceState.APPROVED
                case ApprovalDecision.REJECTED:
                    state = ApprovalEvidenceState.REJECTED
                case _:
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
