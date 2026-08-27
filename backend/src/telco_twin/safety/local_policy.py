"""C1-local policy over trusted observation and simulator provenance."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, assert_never

from telco_twin.counterfactual.comparison import CounterfactualComparison, hash_comparison
from telco_twin.counterfactual.receipt import (
    ReceiptRejected,
    SimulationReceipt,
    revalidate_counterfactual_receipt,
    verify_counterfactual,
)
from telco_twin.domain._contract import Sha256Hex, StrictContract
from telco_twin.domain.canonical import canonical_model_bytes
from telco_twin.safety.policy_models import (
    LOCAL_POLICY_DEFINITION_HASH,
    POLICY_DECISION_ISSUER,
    POLICY_DEFINITION,
    QUALITY_REASONS,
    PolicyAdmission,
    PolicyDecision,
    PolicyDecisionCreationError,
    PolicyDecisionIssuer,
    PolicyDecisionPayload,
    PolicyDecisionRejected,
    PolicyEvaluation,
    PolicyReason,
    PolicyVerification,
    PolicyVerificationCode,
)
from telco_twin.safety.quality_receipt import (
    QualityReceipt,
    QualityReceiptEvidence,
    QualityReceiptRejected,
    issue_quality_receipt,
    quality_receipt_hash,
    revalidate_quality_receipt,
)

if TYPE_CHECKING:
    from telco_twin.counterfactual.runner import CounterfactualRun
    from telco_twin.simulator.metrics import QualityPolicy
    from telco_twin.simulator.network_model import NetworkObservation
    from telco_twin.state.trusted_clock import TrustedClock

__all__ = (
    "LOCAL_POLICY_DEFINITION_HASH",
    "POLICY_DEFINITION",
    "QUALITY_REASONS",
    "LocalPolicyInput",
    "PolicyAdmission",
    "PolicyDecision",
    "PolicyDecisionCreationError",
    "PolicyDecisionIssuer",
    "PolicyDecisionPayload",
    "PolicyDecisionRejected",
    "PolicyEvaluation",
    "PolicyReason",
    "PolicyVerificationCode",
    "evaluate_local_policy",
    "revalidate_policy_decision",
)


@dataclass(frozen=True, slots=True)
class LocalPolicyInput:
    """Actual observation/settings and simulator objects; prose is absent."""

    observation: NetworkObservation
    quality_policy: QualityPolicy
    run: CounterfactualRun | None
    comparison: CounterfactualComparison | None


class _PolicyEvidenceInput(StrictContract):
    eligible: bool
    reasons: tuple[PolicyReason, ...]
    patch_hash: Sha256Hex | None
    simulation_hash: Sha256Hex | None
    quality_hash: Sha256Hex
    policy_definition_hash: Sha256Hex


def _build_evaluation(body: _PolicyEvidenceInput) -> PolicyEvaluation:
    return PolicyEvaluation(
        eligible=body.eligible,
        reasons=body.reasons,
        patch_hash=body.patch_hash,
        simulation_hash=body.simulation_hash,
        quality_hash=body.quality_hash,
        policy_definition_hash=body.policy_definition_hash,
        policy_hash=hashlib.sha256(canonical_model_bytes(body)).hexdigest(),
    )


def _observation_is_bound(policy_input: LocalPolicyInput) -> bool:
    run = policy_input.run
    if run is None:
        return True
    return (
        policy_input.observation.scenario_id == run.baseline_manifest.scenario.scenario_id
        and policy_input.observation.topology_id == run.baseline_manifest.topology.topology_id
    )


def _evaluation_from_receipt(
    policy_input: LocalPolicyInput,
    quality_receipt: QualityReceipt,
) -> tuple[PolicyEvaluation, SimulationReceipt | None]:
    assessment = quality_receipt.evidence.assessment
    reasons = [QUALITY_REASONS[flag] for flag in assessment.flags]
    patch_hash: Sha256Hex | None = None
    simulation_hash: Sha256Hex | None = None
    simulation_receipt: SimulationReceipt | None = None
    if not _observation_is_bound(policy_input):
        reasons.append(PolicyReason.OBSERVATION_BINDING)
    if policy_input.run is None or policy_input.comparison is None:
        reasons.extend(
            (
                PolicyReason.PATCH_HASH_MISSING,
                PolicyReason.SIMULATION_HASH_MISSING,
                PolicyReason.SIMULATION_MISSING,
            )
        )
    else:
        receipt_result = verify_counterfactual(policy_input.run, policy_input.comparison)
        match receipt_result:
            case ReceiptRejected():
                reasons.append(PolicyReason.SIMULATION_PROVENANCE_INVALID)
                patch_hash = policy_input.comparison.result.patch_hash
                simulation_hash = hash_comparison(policy_input.comparison)
            case SimulationReceipt():
                simulation_receipt = receipt_result
                patch_hash = receipt_result.evidence.patch_hash
                simulation_hash = receipt_result.evidence.simulation_hash
            case _:  # pragma: no cover - exhaustive typed union
                assert_never(receipt_result)
    frozen_reasons = tuple(reasons)
    body = _PolicyEvidenceInput(
        eligible=not frozen_reasons,
        reasons=frozen_reasons,
        patch_hash=patch_hash,
        simulation_hash=simulation_hash,
        quality_hash=quality_receipt_hash(quality_receipt),
        policy_definition_hash=LOCAL_POLICY_DEFINITION_HASH,
    )
    return _build_evaluation(body), simulation_receipt


def evaluate_local_policy(
    policy_input: LocalPolicyInput,
    clock: TrustedClock,
) -> PolicyDecision:
    """Recompute observation/simulator provenance and issue a capability."""
    quality_receipt = issue_quality_receipt(
        policy_input.observation,
        policy_input.quality_policy,
        clock,
    )
    evidence, simulation_receipt = _evaluation_from_receipt(
        policy_input,
        quality_receipt,
    )
    payload = PolicyDecisionPayload(
        quality_receipt=quality_receipt,
        simulation_receipt=simulation_receipt,
        evidence=evidence,
    )
    return PolicyDecision(POLICY_DECISION_ISSUER, payload)


def revalidate_policy_decision(
    decision: PolicyDecision,
    clock: TrustedClock,
) -> PolicyVerification:
    """Recompute retained observation, freshness, run, comparison, and evidence."""
    quality_result = revalidate_quality_receipt(decision.quality_receipt, clock)
    match quality_result:
        case QualityReceiptRejected():
            return PolicyDecisionRejected(PolicyVerificationCode.QUALITY_CHANGED)
        case QualityReceiptEvidence():
            pass
        case _:  # pragma: no cover - exhaustive typed union
            assert_never(quality_result)
    simulation_receipt = decision.receipt
    if simulation_receipt is None:
        return PolicyDecisionRejected(PolicyVerificationCode.PROVENANCE_REQUIRED)
    simulation_result = revalidate_counterfactual_receipt(simulation_receipt)
    match simulation_result:
        case ReceiptRejected():
            return PolicyDecisionRejected(PolicyVerificationCode.EVIDENCE_CHANGED)
        case SimulationReceipt():
            policy_input = LocalPolicyInput(
                observation=decision.quality_receipt.observation,
                quality_policy=decision.quality_receipt.policy,
                run=simulation_result.run,
                comparison=simulation_result.comparison,
            )
        case _:  # pragma: no cover - exhaustive typed union
            assert_never(simulation_result)
    evidence, refreshed_receipt = _evaluation_from_receipt(
        policy_input,
        decision.quality_receipt,
    )
    if refreshed_receipt is None or evidence != decision.evidence:
        return PolicyDecisionRejected(PolicyVerificationCode.EVIDENCE_CHANGED)
    return evidence
