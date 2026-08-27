"""Evidence-only approval state-machine tests."""

from dataclasses import replace
from datetime import UTC, datetime
from enum import StrEnum, unique
from typing import ClassVar, assert_never

import anyio
import pytest
from pydantic import BaseModel, ConfigDict

from telco_twin.approval.authority import (
    ApprovalProofIssue,
    ApprovalRequestIssue,
    AuthorityMode,
    SessionIssue,
    issue_approval_request,
    load_approval_authority,
)
from telco_twin.approval.state_machine import (
    ApprovalEvidenceState,
    ApprovalStateError,
    ApprovalStateErrorCode,
    ApprovalStateMachine,
)
from telco_twin.domain.approval import (
    ApprovalDecision,
    ApprovalProof,
    ApprovalRequest,
    ApprovalValidationContext,
    ContractErrorCode,
    ContractViolationError,
    Environment,
)
from telco_twin.safety.local_policy import (
    LOCAL_POLICY_DEFINITION_HASH,
    PolicyEvaluation,
    PolicyEvaluationInput,
    PolicyReason,
)


@unique
class ProofMutation(StrEnum):
    PATCH = "patch"
    REQUEST = "request"
    SIGNATURE = "signature"
    FUTURE = "future"
    EXPIRED = "expired"


class _MutationInput(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    mutation: ProofMutation


def _policy(*, eligible: bool = True) -> PolicyEvaluation:
    return PolicyEvaluation.build(
        PolicyEvaluationInput(
            eligible=eligible,
            reasons=() if eligible else (PolicyReason.UNSAFE_CONSTRAINT,),
            patch_hash="a" * 64,
            simulation_hash="b" * 64,
            policy_definition_hash=LOCAL_POLICY_DEFINITION_HASH,
        )
    )


def approval_chain() -> tuple[
    PolicyEvaluation,
    ApprovalRequest,
    ApprovalProof,
    ApprovalValidationContext,
]:
    authority = load_approval_authority(AuthorityMode.LOCAL)
    session = authority.issue_session(
        SessionIssue(session_id="session-0001", issued_at="2026-08-27T00:00:00Z")
    )
    policy = _policy()
    request = issue_approval_request(
        ApprovalRequestIssue(
            request_id="approval-request-0001",
            session_id="session-0001",
            patch_hash="a" * 64,
            simulation_hash="b" * 64,
            policy_hash=policy.policy_hash,
            requested_at="2026-08-27T00:00:00Z",
            nonce=b"\x01" * 16,
        )
    )
    proof = session.issue_proof(
        ApprovalProofIssue(
            request=request,
            decision=ApprovalDecision.APPROVED,
            proof_id="approval-proof-0001",
            approved_at="2026-08-27T00:00:00Z",
        )
    )
    context = ApprovalValidationContext(
        root=authority.descriptor,
        certificate=session.certificate,
        request=request,
        environment=Environment.TEST,
        trusted_root_hashes=frozenset({authority.descriptor.descriptor_hash}),
        consumed_nonces=frozenset(),
        now=datetime(2026, 8, 27, 0, 0, 30, tzinfo=UTC),
    )
    return policy, request, proof, context


def _rejected_chain() -> tuple[
    PolicyEvaluation,
    ApprovalRequest,
    ApprovalProof,
    ApprovalValidationContext,
]:
    authority = load_approval_authority(AuthorityMode.LOCAL)
    session = authority.issue_session(
        SessionIssue(session_id="session-0001", issued_at="2026-08-27T00:00:00Z")
    )
    policy = _policy()
    request = issue_approval_request(
        ApprovalRequestIssue(
            request_id="approval-request-0001",
            session_id="session-0001",
            patch_hash="a" * 64,
            simulation_hash="b" * 64,
            policy_hash=policy.policy_hash,
            requested_at="2026-08-27T00:00:00Z",
            nonce=b"\x02" * 16,
        )
    )
    proof = session.issue_proof(
        ApprovalProofIssue(
            request=request,
            decision=ApprovalDecision.REJECTED,
            proof_id="approval-proof-0002",
            approved_at="2026-08-27T00:00:00Z",
        )
    )
    context = ApprovalValidationContext(
        root=authority.descriptor,
        certificate=session.certificate,
        request=request,
        environment=Environment.TEST,
        trusted_root_hashes=frozenset({authority.descriptor.descriptor_hash}),
        consumed_nonces=frozenset(),
        now=datetime(2026, 8, 27, 0, 0, 30, tzinfo=UTC),
    )
    return policy, request, proof, context


def test_valid_proof_advances_pending_to_evidence_only_approved() -> None:
    async def scenario() -> None:
        # Given: a request admitted by an eligible local-policy result.
        policy, request, proof, context = approval_chain()
        machine = ApprovalStateMachine()
        pending = await machine.record_request(request, policy)
        # When: the matching root-certified session proof is recorded.
        approved = await machine.record_proof(proof, context)
        # Then: only evidence state advances and the proof hash is retained.
        assert pending.state is ApprovalEvidenceState.PENDING
        assert approved.state is ApprovalEvidenceState.APPROVED
        assert approved.proof_hash is not None

    anyio.run(scenario)


def test_missing_simulation_policy_evidence_never_creates_pending_state() -> None:
    async def scenario() -> None:
        # Given: a valid-shaped request but an ineligible fail-closed policy result.
        _, request, _, _ = approval_chain()
        machine = ApprovalStateMachine()
        # When: request admission is attempted without eligible simulation evidence.
        with pytest.raises(ApprovalStateError) as caught:
            _ = await machine.record_request(request, _policy(eligible=False))
        # Then: the stable evidence-required code is returned.
        assert caught.value.code is ApprovalStateErrorCode.POLICY_INELIGIBLE

    anyio.run(scenario)


def test_changed_patch_simulation_or_policy_hash_never_creates_pending_state() -> None:
    async def scenario() -> None:
        # Given: eligible policy evidence and a request whose patch hash was changed.
        policy, request, _, _ = approval_chain()
        changed = request.model_copy(update={"patch_hash": "f" * 64})
        machine = ApprovalStateMachine()
        # When: admission compares request bindings with policy output.
        with pytest.raises(ApprovalStateError) as caught:
            _ = await machine.record_request(changed, policy)
        # Then: changed evidence cannot become pending.
        assert caught.value.code is ApprovalStateErrorCode.EVIDENCE_BINDING_MISMATCH

    anyio.run(scenario)


def test_valid_rejection_proof_advances_only_to_rejected_evidence() -> None:
    async def scenario() -> None:
        # Given: an admitted request and a valid session-signed rejection decision.
        policy, request, proof, context = _rejected_chain()
        machine = ApprovalStateMachine()
        _ = await machine.record_request(request, policy)
        # When: the rejection proof is recorded.
        result = await machine.record_proof(proof, context)
        # Then: the terminal state is rejected evidence, never execution authority.
        assert result.state is ApprovalEvidenceState.REJECTED

    anyio.run(scenario)


def test_cross_session_certificate_is_rejected() -> None:
    async def scenario() -> None:
        # Given: a pending request and a certificate for a different session.
        policy, request, proof, context = approval_chain()
        other_session = load_approval_authority(AuthorityMode.LOCAL).issue_session(
            SessionIssue(session_id="session-0002", issued_at="2026-08-27T00:00:00Z")
        )
        machine = ApprovalStateMachine()
        _ = await machine.record_request(request, policy)
        # When: the proof is paired with the cross-session certificate.
        with pytest.raises(ContractViolationError) as caught:
            _ = await machine.record_proof(
                proof,
                replace(context, certificate=other_session.certificate),
            )
        # Then: session binding fails before any evidence transition.
        assert caught.value.code is ContractErrorCode.CERTIFICATE_BINDING_MISMATCH

    anyio.run(scenario)


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        (ProofMutation.PATCH, ContractErrorCode.APPROVAL_BINDING_MISMATCH),
        (ProofMutation.REQUEST, ContractErrorCode.APPROVAL_BINDING_MISMATCH),
        (ProofMutation.SIGNATURE, ContractErrorCode.PROOF_SIGNATURE_INVALID),
        (ProofMutation.FUTURE, ContractErrorCode.APPROVAL_NOT_YET_VALID),
        (ProofMutation.EXPIRED, ContractErrorCode.APPROVAL_EXPIRED),
    ],
)
def test_altered_forged_future_or_expired_proof_is_rejected(
    mutation: ProofMutation,
    expected: ContractErrorCode,
) -> None:
    async def scenario() -> None:
        # Given: one pending request and one valid signed proof.
        policy, request, proof, context = approval_chain()
        machine = ApprovalStateMachine()
        _ = await machine.record_request(request, policy)
        candidate = proof
        candidate_context = context
        mutation_input = _MutationInput(mutation=mutation)
        match mutation_input.mutation:
            case ProofMutation.PATCH:
                candidate = proof.model_copy(update={"patch_hash": "d" * 64})
            case ProofMutation.REQUEST:
                candidate = proof.model_copy(
                    update={"approval_request_id": "approval-request-other"}
                )
            case ProofMutation.SIGNATURE:
                candidate = proof.model_copy(update={"proof_signature": "A" * 86})
            case ProofMutation.FUTURE:
                candidate_context = replace(
                    context,
                    now=datetime(2026, 8, 26, 23, 59, 59, tzinfo=UTC),
                )
            case ProofMutation.EXPIRED:
                candidate_context = replace(
                    context,
                    now=datetime(2026, 8, 27, 0, 1, 1, tzinfo=UTC),
                )
            case _:
                assert_never(mutation_input.mutation)
        # When: the invalid proof attempts a state transition.
        with pytest.raises(ContractViolationError) as caught:
            _ = await machine.record_proof(candidate, candidate_context)
        # Then: the expected stable chain code blocks approval.
        assert caught.value.code is expected

    anyio.run(scenario)


def test_nonce_is_one_use_across_repeated_proof_submission() -> None:
    async def scenario() -> None:
        # Given: a proof that has already advanced its request.
        policy, request, proof, context = approval_chain()
        machine = ApprovalStateMachine()
        _ = await machine.record_request(request, policy)
        _ = await machine.record_proof(proof, context)
        # When: the exact proof nonce is submitted again.
        with pytest.raises(ContractViolationError) as caught:
            _ = await machine.record_proof(proof, context)
        # Then: replay is distinguished from an ordinary state conflict.
        assert caught.value.code is ContractErrorCode.NONCE_REPLAYED

    anyio.run(scenario)


def test_state_machine_has_no_revocation_or_network_transition_surface() -> None:
    # Given: the evidence-only state-machine public API.
    names = frozenset(
        name.lower() for name in dir(ApprovalStateMachine) if not name.startswith("_")
    )
    # When: prohibited authority names are checked.
    prohibited = names & {"execute", "apply", "commit", "revoke", "revocation"}
    # Then: only request/proof evidence recording exists.
    assert prohibited == frozenset()
