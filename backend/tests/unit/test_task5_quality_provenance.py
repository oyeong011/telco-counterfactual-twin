"""Trusted observation-quality provenance regressions."""

from datetime import UTC, datetime
from pathlib import Path

import anyio
import pytest

from telco_twin.approval.authority import (
    ApprovalProofIssue,
    ApprovalRequestIssue,
    AuthorityMode,
    SessionIssue,
    issue_approval_request,
    load_approval_authority,
)
from telco_twin.approval.state_machine import ApprovalStateError
from telco_twin.domain.approval import (
    ApprovalDecision,
    ApprovalValidationContext,
    Environment,
)
from telco_twin.safety.local_policy import (
    LocalPolicyInput,
    PolicyReason,
    evaluate_local_policy,
)
from telco_twin.safety.quality_receipt import (
    QualityReceipt,
    QualityReceiptCreationError,
    QualityReceiptErrorCode,
    QualityReceiptIssuer,
    QualityReceiptPayload,
    QualityReceiptRejected,
    revalidate_quality_receipt,
)
from telco_twin.simulator.metrics import QualityContext, QualityPolicy, assess_observation_quality
from telco_twin.simulator.network_model import (
    NetworkObservation,
    load_scenario_manifests,
)
from telco_twin.state.trusted_clock import FixedClock

from .approval_test_support import MutableClock, machine_for
from .test_local_policy import local_policy_input

FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "fixtures/scenarios"
OBSERVED_AT = "2026-08-27T00:00:00Z"


def _observation_for_policy() -> NetworkObservation:
    policy_input = local_policy_input()
    assert policy_input.run is not None
    source = load_scenario_manifests(FIXTURE_ROOT)[0].observation
    return source.model_copy(
        update={
            "scenario_id": policy_input.run.baseline_manifest.scenario.scenario_id,
            "topology_id": policy_input.run.baseline_manifest.topology.topology_id,
            "windows": tuple(
                window.model_copy(update={"observed_at": OBSERVED_AT}) for window in source.windows
            ),
            "alarms": tuple(
                alarm.model_copy(update={"observed_at": OBSERVED_AT}) for alarm in source.alarms
            ),
            "config_history": tuple(
                config.model_copy(update={"recorded_at": OBSERVED_AT})
                for config in source.config_history
            ),
        }
    )


def test_stale_observation_cannot_be_cleaned_by_caller_assessment() -> None:
    # Given: genuinely stale evidence and a caller-created clean assessment.
    observation = _observation_for_policy()
    policy_input = local_policy_input()
    quality_policy = QualityPolicy(max_age_seconds=10)
    stale = assess_observation_quality(
        observation,
        QualityContext(
            assessed_at="2026-08-27T00:00:30Z",
            policy=quality_policy,
        ),
    )
    assert stale.approval_eligible is False
    # When: policy receives the actual observation under trusted stale time.
    decision = evaluate_local_policy(
        LocalPolicyInput(
            observation=observation,
            quality_policy=quality_policy,
            run=policy_input.run,
            comparison=policy_input.comparison,
        ),
        FixedClock(STALE_TIME),
    )
    # Then: trusted freshness blocks eligibility despite the caller's clean assessment.
    assert decision.evidence.eligible is False
    assert PolicyReason.OBSERVATION_STALE in decision.evidence.reasons


def test_observation_identity_must_match_counterfactual_scenario() -> None:
    policy_input = local_policy_input()
    changed = policy_input.observation.model_copy(
        update={"scenario_id": "scenario-observation-other"}
    )
    decision = evaluate_local_policy(
        LocalPolicyInput(
            observation=changed,
            quality_policy=policy_input.quality_policy,
            run=policy_input.run,
            comparison=policy_input.comparison,
        ),
        FixedClock(ISSUE_TIME),
    )
    assert PolicyReason.OBSERVATION_BINDING in decision.evidence.reasons


def test_quality_receipt_rejects_external_construction_and_evidence_mutation() -> None:
    decision = evaluate_local_policy(local_policy_input(), FixedClock(ISSUE_TIME))
    receipt = decision.quality_receipt
    model_methods = {"model_validate", "model_copy", "model_dump", "model_dump_json"}
    assert not any(hasattr(receipt, name) for name in model_methods)
    with pytest.raises(QualityReceiptCreationError):
        _ = QualityReceipt(
            QualityReceiptIssuer(),
            QualityReceiptPayload(
                observation=receipt.observation,
                policy=receipt.policy,
                evidence=receipt.evidence,
            ),
        )
    object.__setattr__(receipt.evidence, "context_hash", "0" * 64)
    result = revalidate_quality_receipt(receipt, FixedClock(ISSUE_TIME))
    assert result == QualityReceiptRejected(QualityReceiptErrorCode.EVIDENCE_CHANGED)


ISSUE_TIME = datetime(2026, 8, 27, 0, 0, 5, tzinfo=UTC)
STALE_TIME = datetime(2026, 8, 27, 0, 0, 30, tzinfo=UTC)


def test_quality_is_rechecked_when_time_advances_between_pending_and_proof() -> None:
    async def scenario() -> None:
        # Given: evidence fresh at pending admission under a ten-second policy.
        clock = MutableClock(ISSUE_TIME)
        observation = _observation_for_policy()
        quality_policy = QualityPolicy(max_age_seconds=10)
        initial = assess_observation_quality(
            observation,
            QualityContext(
                assessed_at="2026-08-27T00:00:05Z",
                policy=quality_policy,
            ),
        )
        assert initial.approval_eligible is True
        policy_input = local_policy_input(
            observation=observation,
            quality_policy=quality_policy,
        )
        policy = evaluate_local_policy(policy_input, clock)
        evidence = policy.evidence
        assert evidence.patch_hash is not None
        assert evidence.simulation_hash is not None
        authority = load_approval_authority(AuthorityMode.LOCAL)
        session = authority.issue_session(
            SessionIssue(session_id="session-quality-time", issued_at=OBSERVED_AT)
        )
        request = issue_approval_request(
            ApprovalRequestIssue(
                request_id="approval-quality-time",
                session_id="session-quality-time",
                patch_hash=evidence.patch_hash,
                simulation_hash=evidence.simulation_hash,
                policy_hash=evidence.policy_hash,
                requested_at=OBSERVED_AT,
                nonce=b"\x07" * 16,
            )
        )
        proof = session.issue_proof(
            ApprovalProofIssue(
                request=request,
                decision=ApprovalDecision.APPROVED,
                proof_id="proof-quality-time",
                approved_at=OBSERVED_AT,
            )
        )
        context = ApprovalValidationContext(
            root=authority.descriptor,
            certificate=session.certificate,
            request=request,
            environment=Environment.TEST,
            trusted_root_hashes=frozenset({authority.descriptor.descriptor_hash}),
            consumed_nonces=frozenset(),
            now=clock.now(),
        )
        machine = machine_for(context, clock)
        _ = await machine.record_request(request, policy, session.certificate)
        # When: trusted time advances while the proof itself remains valid.
        clock.advance_to(STALE_TIME)
        # Then: proof-time freshness, not the earlier clean flag, blocks approval.
        with pytest.raises(ApprovalStateError):
            _ = await machine.record_proof(proof)

    anyio.run(scenario)
