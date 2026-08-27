"""Evidence-only approval state-machine tests."""

from datetime import UTC, datetime
from enum import StrEnum, unique
from typing import assert_never

import anyio
import pytest

from telco_twin.approval.authority import AuthorityMode, SessionIssue, load_approval_authority
from telco_twin.approval.state_machine import (
    ApprovalEvidenceState,
    ApprovalStateError,
    ApprovalStateErrorCode,
    ApprovalStateMachine,
)
from telco_twin.domain.approval import ContractErrorCode, ContractViolationError
from telco_twin.safety.local_policy import LocalPolicyInput, evaluate_local_policy
from telco_twin.state.trusted_clock import FixedClock

from .approval_test_support import (
    MutableClock,
    approval_chain,
    machine_for,
    rejected_chain,
)
from .test_local_policy import POLICY_TIME, local_policy_input


@unique
class ProofMutation(StrEnum):
    PATCH = "patch"
    REQUEST = "request"
    SIGNATURE = "signature"
    FUTURE = "future"
    EXPIRED = "expired"


def test_valid_proof_advances_pending_to_evidence_only_approved() -> None:
    async def scenario() -> None:
        policy, request, proof, context = approval_chain()
        machine = machine_for(context)
        pending = await machine.record_request(request, policy, context.certificate)
        approved = await machine.record_proof(proof)
        assert pending.state is ApprovalEvidenceState.PENDING
        assert approved.state is ApprovalEvidenceState.APPROVED
        assert approved.proof_hash is not None

    anyio.run(scenario)


def test_missing_simulation_policy_evidence_never_creates_pending_state() -> None:
    async def scenario() -> None:
        _, request, _, context = approval_chain()
        source = local_policy_input()
        policy = evaluate_local_policy(
            LocalPolicyInput(
                observation=source.observation,
                quality_policy=source.quality_policy,
                run=None,
                comparison=None,
            ),
            FixedClock(POLICY_TIME),
        )
        with pytest.raises(ApprovalStateError) as caught:
            _ = await machine_for(context).record_request(
                request,
                policy,
                context.certificate,
            )
        assert caught.value.code is ApprovalStateErrorCode.POLICY_PROVENANCE_REQUIRED

    anyio.run(scenario)


def test_changed_patch_simulation_or_policy_hash_never_creates_pending_state() -> None:
    async def scenario() -> None:
        policy, request, _, context = approval_chain()
        changed = request.model_copy(update={"patch_hash": "f" * 64})
        with pytest.raises(ApprovalStateError) as caught:
            _ = await machine_for(context).record_request(
                changed,
                policy,
                context.certificate,
            )
        assert caught.value.code is ApprovalStateErrorCode.EVIDENCE_BINDING_MISMATCH

    anyio.run(scenario)


def test_valid_rejection_proof_advances_only_to_rejected_evidence() -> None:
    async def scenario() -> None:
        policy, request, proof, context = rejected_chain()
        machine = machine_for(context)
        _ = await machine.record_request(request, policy, context.certificate)
        result = await machine.record_proof(proof)
        assert result.state is ApprovalEvidenceState.REJECTED

    anyio.run(scenario)


def test_cross_session_certificate_is_rejected() -> None:
    async def scenario() -> None:
        policy, request, _, context = approval_chain()
        other = load_approval_authority(AuthorityMode.LOCAL).issue_session(
            SessionIssue(session_id="session-0002", issued_at=request.requested_at)
        )
        with pytest.raises(ApprovalStateError) as caught:
            _ = await machine_for(context).record_request(
                request,
                policy,
                other.certificate,
            )
        assert caught.value.code is ApprovalStateErrorCode.EVIDENCE_BINDING_MISMATCH

    anyio.run(scenario)


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        (ProofMutation.PATCH, ContractErrorCode.APPROVAL_BINDING_MISMATCH),
        (ProofMutation.REQUEST, ApprovalStateErrorCode.REQUEST_UNKNOWN),
        (ProofMutation.SIGNATURE, ContractErrorCode.PROOF_SIGNATURE_INVALID),
        (ProofMutation.FUTURE, ContractErrorCode.APPROVAL_NOT_YET_VALID),
        (ProofMutation.EXPIRED, ContractErrorCode.APPROVAL_EXPIRED),
    ],
)
def test_altered_forged_future_or_expired_proof_is_rejected(
    mutation: ProofMutation,
    expected: ContractErrorCode | ApprovalStateErrorCode,
) -> None:
    async def scenario() -> None:
        policy, request, proof, context = approval_chain()
        clock = MutableClock(context.now)
        machine = machine_for(context, clock)
        _ = await machine.record_request(request, policy, context.certificate)
        candidate = proof
        match mutation:
            case ProofMutation.PATCH:
                candidate = proof.model_copy(update={"patch_hash": "d" * 64})
            case ProofMutation.REQUEST:
                candidate = proof.model_copy(
                    update={"approval_request_id": "approval-request-other"}
                )
            case ProofMutation.SIGNATURE:
                candidate = proof.model_copy(update={"proof_signature": "A" * 86})
            case ProofMutation.FUTURE:
                clock.advance_to(datetime(2026, 8, 26, 23, 59, 59, tzinfo=UTC))
            case ProofMutation.EXPIRED:
                clock.advance_to(datetime(2026, 8, 27, 0, 1, 1, tzinfo=UTC))
            case _:
                assert_never(mutation)
        code: ContractErrorCode | ApprovalStateErrorCode
        try:
            _ = await machine.record_proof(candidate)
        except ContractViolationError as error:
            code = error.code
        except ApprovalStateError as error:
            code = error.code
        else:
            pytest.fail("invalid proof reached terminal evidence")
        assert code is expected

    anyio.run(scenario)


def test_nonce_is_one_use_across_repeated_proof_submission() -> None:
    async def scenario() -> None:
        policy, request, proof, context = approval_chain()
        machine = machine_for(context)
        _ = await machine.record_request(request, policy, context.certificate)
        _ = await machine.record_proof(proof)
        with pytest.raises(ContractViolationError) as caught:
            _ = await machine.record_proof(proof)
        assert caught.value.code is ContractErrorCode.NONCE_REPLAYED

    anyio.run(scenario)


def test_state_machine_has_no_revocation_or_network_transition_surface() -> None:
    names = frozenset(
        name.lower() for name in dir(ApprovalStateMachine) if not name.startswith("_")
    )
    assert names & {"execute", "apply", "commit", "revoke", "revocation"} == frozenset()
