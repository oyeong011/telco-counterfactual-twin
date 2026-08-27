"""Adversarial policy provenance regressions."""

import hashlib
from datetime import UTC, datetime

import anyio
import pytest

from telco_twin.approval.authority import ApprovalRequestIssue, issue_approval_request
from telco_twin.approval.state_machine import (
    ApprovalStateError,
    ApprovalStateErrorCode,
)
from telco_twin.domain.approval import ApprovalRequest
from telco_twin.domain.canonical import canonical_model_bytes
from telco_twin.safety.local_policy import (
    LOCAL_POLICY_DEFINITION_HASH,
    LocalPolicyInput,
    PolicyDecision,
    PolicyDecisionCreationError,
    PolicyDecisionIssuer,
    PolicyDecisionPayload,
    PolicyDecisionRejected,
    PolicyEvaluation,
    PolicyVerificationCode,
    evaluate_local_policy,
    revalidate_policy_decision,
)
from telco_twin.state.trusted_clock import FixedClock

from .approval_test_support import approval_chain, machine_for
from .test_local_policy import POLICY_TIME, local_policy_input, real_policy_decision


def _arbitrary_eligible_policy() -> PolicyEvaluation:
    draft = PolicyEvaluation.model_construct(
        eligible=True,
        reasons=(),
        patch_hash="a" * 64,
        simulation_hash="b" * 64,
        quality_hash="d" * 64,
        policy_definition_hash=LOCAL_POLICY_DEFINITION_HASH,
        policy_hash="0" * 64,
    )
    forged = draft.model_copy(
        update={
            "policy_hash": hashlib.sha256(
                canonical_model_bytes(draft, exclude=frozenset({"policy_hash"}))
            ).hexdigest()
        }
    )
    return PolicyEvaluation.model_validate_json(forged.model_dump_json())


def _request(policy: PolicyEvaluation) -> ApprovalRequest:
    return issue_approval_request(
        ApprovalRequestIssue(
            request_id="approval-request-forged",
            session_id="session-forged",
            patch_hash=policy.patch_hash or "a" * 64,
            simulation_hash=policy.simulation_hash or "b" * 64,
            policy_hash=policy.policy_hash,
            requested_at="2026-08-27T00:00:00Z",
            nonce=b"\x0a" * 16,
        )
    )


def test_policy_evaluation_has_no_public_eligible_builder() -> None:
    # Given: the serializable policy evidence boundary.
    # When: its public class surface is inspected.
    # Then: clients cannot mint eligible evidence with arbitrary hashes.
    assert not hasattr(PolicyEvaluation, "build")


def test_internal_policy_capability_is_not_a_serializable_boundary_model() -> None:
    # Given: a real evaluator-issued capability and its separate evidence projection.
    decision = real_policy_decision()
    encoded = decision.evidence.model_dump_json()
    # When: ordinary boundary construction/copy methods are inspected.
    model_methods = {"model_validate", "model_copy", "model_dump", "model_dump_json"}
    # Then: only evidence round-trips; the internal capability cannot.
    assert not any(hasattr(decision, name) for name in model_methods)
    assert PolicyEvaluation.model_validate_json(encoded) == decision.evidence


def test_policy_capability_rejects_non_module_issuer() -> None:
    # Given: real receipt/evidence combined with a different issuer identity.
    decision = real_policy_decision()
    payload = PolicyDecisionPayload(
        quality_receipt=decision.quality_receipt,
        simulation_receipt=decision.receipt,
        evidence=decision.evidence,
    )
    # When/Then: ordinary direct construction cannot mint the capability.
    with pytest.raises(PolicyDecisionCreationError):
        _ = PolicyDecision(PolicyDecisionIssuer(), payload)


def test_policy_revalidation_rejects_mutated_serializable_evidence() -> None:
    # Given: a real capability whose evidence object is forcibly changed in memory.
    decision = real_policy_decision()
    object.__setattr__(decision.evidence, "policy_hash", "0" * 64)
    # When: state-level provenance is recomputed.
    result = revalidate_policy_decision(decision, FixedClock(POLICY_TIME))
    # Then: the changed serialized projection fails closed.
    assert result == PolicyDecisionRejected(PolicyVerificationCode.EVIDENCE_CHANGED)


def test_arbitrary_eligible_policy_without_simulator_never_reaches_pending() -> None:
    async def scenario() -> None:
        # Given: a self-hashed eligible object created without runner/comparison/evaluator calls.
        policy = _arbitrary_eligible_policy()
        _, _, _, context = approval_chain()
        machine = machine_for(context)
        # When: request admission receives only fabricated serializable evidence.
        with pytest.raises(ApprovalStateError):
            _ = await machine.record_request(_request(policy), policy, context.certificate)

    anyio.run(scenario)


def test_deserialized_eligible_policy_without_simulator_never_reaches_pending() -> None:
    async def scenario() -> None:
        # Given: fabricated eligible evidence round-tripped through the public JSON boundary.
        source = _arbitrary_eligible_policy()
        policy = PolicyEvaluation.model_validate_json(source.model_dump_json())
        _, _, _, context = approval_chain()
        machine = machine_for(context)
        # When: deserialized evidence is presented as approval provenance.
        with pytest.raises(ApprovalStateError):
            _ = await machine.record_request(_request(policy), policy, context.certificate)

    anyio.run(scenario)


def test_model_copy_eligible_policy_without_simulator_never_reaches_pending() -> None:
    async def scenario() -> None:
        # Given: a copied/rehashed eligible model with no simulator-owned capability.
        source = _arbitrary_eligible_policy()
        draft = source.model_copy(update={"simulation_hash": "c" * 64, "policy_hash": "0" * 64})
        policy = draft.model_copy(
            update={
                "policy_hash": hashlib.sha256(
                    canonical_model_bytes(draft, exclude=frozenset({"policy_hash"}))
                ).hexdigest()
            }
        )
        _, _, _, context = approval_chain()
        machine = machine_for(context)
        # When: model-copy forgery is presented as approval provenance.
        with pytest.raises(ApprovalStateError):
            _ = await machine.record_request(_request(policy), policy, context.certificate)

    anyio.run(scenario)


def test_changed_comparison_cannot_rebind_into_policy_eligibility() -> None:
    # Given: a real comparison whose candidate metric is changed after simulation.
    policy_input = local_policy_input()
    assert policy_input.comparison is not None
    first_delta = policy_input.comparison.result.metric_deltas[0]
    changed_result = policy_input.comparison.result.model_copy(
        update={
            "metric_deltas": (
                first_delta.model_copy(update={"candidate": first_delta.candidate + 1}),
                *policy_input.comparison.result.metric_deltas[1:],
            )
        }
    )
    comparison = policy_input.comparison.model_copy(update={"result": changed_result})
    # When: the changed comparison is evaluated with the original run.
    policy = evaluate_local_policy(
        LocalPolicyInput(
            observation=policy_input.observation,
            quality_policy=policy_input.quality_policy,
            run=policy_input.run,
            comparison=comparison,
        ),
        FixedClock(POLICY_TIME),
    ).evidence
    # Then: simulator provenance, not caller-recomputed hashes, controls eligibility.
    assert policy.eligible is False


def test_zero_event_equivalent_comparison_cannot_be_policy_eligible() -> None:
    # Given: a model-copy comparison stripped of all simulator result evidence.
    policy_input = local_policy_input()
    assert policy_input.comparison is not None
    empty_result = policy_input.comparison.result.model_copy(
        update={"metric_deltas": (), "constraints": (), "approval_eligible": True}
    )
    comparison = policy_input.comparison.model_copy(update={"result": empty_result})
    # When: the zero-evidence comparison is evaluated.
    policy = evaluate_local_policy(
        LocalPolicyInput(
            observation=policy_input.observation,
            quality_policy=policy_input.quality_policy,
            run=policy_input.run,
            comparison=comparison,
        ),
        FixedClock(POLICY_TIME),
    ).evidence
    # Then: empty simulator evidence is fail-closed.
    assert policy.eligible is False


def test_state_revalidates_receipt_again_before_recording_proof() -> None:
    async def scenario() -> None:
        # Given: pending state whose retained baseline is mutated after admission.
        policy, request, proof, context = approval_chain()
        machine = machine_for(context)
        _ = await machine.record_request(request, policy, context.certificate)
        assert policy.receipt is not None
        policy.receipt.run.baseline_manifest.topology.nodes[0].attributes["capacity_ues"] = 999
        # When/Then: proof recording re-runs provenance and fails closed.
        with pytest.raises(ApprovalStateError):
            _ = await machine.record_proof(proof)

    anyio.run(scenario)


def test_ineligible_policy_with_real_receipt_never_creates_pending_state() -> None:
    async def scenario() -> None:
        # Given: real simulator provenance with stale observation quality.
        _, request, _, context = approval_chain()
        policy = real_policy_decision(clock=FixedClock(datetime(2026, 8, 27, 0, 5, 0, tzinfo=UTC)))
        # When: approval admission revalidates the decision.
        with pytest.raises(ApprovalStateError) as caught:
            _ = await machine_for(context).record_request(
                request,
                policy,
                context.certificate,
            )
        # Then: provenance remains necessary but cannot override ineligibility.
        assert caught.value.code is ApprovalStateErrorCode.POLICY_INELIGIBLE

    anyio.run(scenario)
