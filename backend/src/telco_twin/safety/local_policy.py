"""C1-local policy over recomputed simulator provenance and typed quality."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum, unique
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, Self, assert_never, final, override

from pydantic import model_validator

from telco_twin.counterfactual.comparison import CounterfactualComparison, hash_comparison
from telco_twin.counterfactual.receipt import (
    ReceiptRejected,
    SimulationReceipt,
    revalidate_counterfactual_receipt,
    verify_counterfactual,
)
from telco_twin.domain._contract import Sha256Hex, StrictContract
from telco_twin.domain._validation import fail_validation
from telco_twin.domain.canonical import canonical_model_bytes
from telco_twin.simulator.metrics import ObservationQualityFlag, QualityAssessment

if TYPE_CHECKING:
    from telco_twin.counterfactual.runner import CounterfactualRun


class _PolicyDefinition(StrictContract):
    policy_id: str
    version: str
    require_fresh_observation: bool
    require_all_constraints: bool
    require_simulator_receipt: bool


POLICY_DEFINITION = _PolicyDefinition(
    policy_id="c1-local-safety",
    version="1.1.0",
    require_fresh_observation=True,
    require_all_constraints=True,
    require_simulator_receipt=True,
)
LOCAL_POLICY_DEFINITION_HASH: Sha256Hex = hashlib.sha256(
    canonical_model_bytes(POLICY_DEFINITION)
).hexdigest()


@unique
class PolicyReason(StrEnum):
    """Stable fail-closed local policy reasons."""

    OBSERVATION_STALE = "observation-stale"
    OBSERVATION_FUTURE = "observation-future"
    OBSERVATION_NOISY = "observation-noisy"
    UNSAFE_CONSTRAINT = "unsafe-constraint"
    PATCH_HASH_MISSING = "patch-hash-missing"
    SIMULATION_MISSING = "simulation-missing"
    SIMULATION_HASH_MISSING = "simulation-hash-missing"
    SIMULATION_PROVENANCE_INVALID = "simulation-provenance-invalid"


QUALITY_REASONS: Final = MappingProxyType(
    {
        ObservationQualityFlag.STALE: PolicyReason.OBSERVATION_STALE,
        ObservationQualityFlag.FUTURE: PolicyReason.OBSERVATION_FUTURE,
        ObservationQualityFlag.NOISY: PolicyReason.OBSERVATION_NOISY,
    }
)


@dataclass(frozen=True, slots=True)
class LocalPolicyInput:
    """Internal input retaining actual run/comparison objects, never prose."""

    quality: QualityAssessment
    run: CounterfactualRun | None
    comparison: CounterfactualComparison | None


class _PolicyEvaluationBody(StrictContract):
    eligible: bool
    reasons: tuple[PolicyReason, ...]
    patch_hash: Sha256Hex | None
    simulation_hash: Sha256Hex | None
    policy_definition_hash: Sha256Hex


class PolicyEvaluation(_PolicyEvaluationBody):
    """Serializable policy evidence; never sufficient approval provenance."""

    policy_hash: Sha256Hex

    @model_validator(mode="after")
    def hash_and_eligibility_are_consistent(self) -> Self:
        """Reject altered evidence and success without simulator identities."""
        expected = hashlib.sha256(
            canonical_model_bytes(self, exclude=frozenset({"policy_hash"}))
        ).hexdigest()
        if self.policy_hash != expected:
            fail_validation("policy_hash_mismatch", "local policy result hash mismatch")
        if self.eligible and (
            self.reasons or self.patch_hash is None or self.simulation_hash is None
        ):
            fail_validation("policy_eligibility", "eligible policy result lacks exact evidence")
        if not self.eligible and not self.reasons:
            fail_validation("policy_reasons", "ineligible policy result requires a reason")
        return self


@dataclass(frozen=True, slots=True)
class PolicyDecisionIssuer:
    """Module identity unavailable to parsing/model-copy boundaries."""


_DECISION_ISSUER = PolicyDecisionIssuer()


@dataclass(frozen=True, slots=True)
class PolicyDecisionPayload:
    """Immutable evaluator inputs retained by the internal capability."""

    quality: QualityAssessment
    receipt: SimulationReceipt | None
    evidence: PolicyEvaluation


@dataclass(frozen=True, slots=True)
class PolicyDecisionCreationError(Exception):
    """A caller attempted to construct provenance outside evaluation."""

    @override
    def __str__(self) -> str:
        return "policy-decision-construction-forbidden"


@final
class PolicyDecision:
    """Internal provenance capability with separate serializable evidence."""

    __slots__ = ("_payload",)

    def __init__(
        self,
        issuer: PolicyDecisionIssuer,
        payload: PolicyDecisionPayload,
    ) -> None:
        """Accept construction only from the local evaluator."""
        if issuer is not _DECISION_ISSUER:
            raise PolicyDecisionCreationError
        self._payload = payload

    @property
    def evidence(self) -> PolicyEvaluation:
        """Return the serializable evidence projection."""
        return self._payload.evidence

    @property
    def receipt(self) -> SimulationReceipt | None:
        """Return the retained simulator receipt for state revalidation."""
        return self._payload.receipt

    @property
    def quality(self) -> QualityAssessment:
        """Return the typed observation quality bound into this decision."""
        return self._payload.quality


type PolicyAdmission = PolicyDecision | PolicyEvaluation


@unique
class PolicyVerificationCode(StrEnum):
    """Stable failures when approval re-resolves provenance."""

    PROVENANCE_REQUIRED = "policy-provenance-required"
    EVIDENCE_CHANGED = "policy-evidence-changed"


@dataclass(frozen=True, slots=True)
class PolicyDecisionRejected:
    """Fail-closed provenance revalidation result."""

    code: PolicyVerificationCode


type PolicyVerification = PolicyEvaluation | PolicyDecisionRejected


def _quality_reason(flag: ObservationQualityFlag) -> PolicyReason:
    return QUALITY_REASONS[flag]


def _build_evaluation(body: _PolicyEvaluationBody) -> PolicyEvaluation:
    return PolicyEvaluation(
        eligible=body.eligible,
        reasons=body.reasons,
        patch_hash=body.patch_hash,
        simulation_hash=body.simulation_hash,
        policy_definition_hash=body.policy_definition_hash,
        policy_hash=hashlib.sha256(canonical_model_bytes(body)).hexdigest(),
    )


def _evaluate(policy_input: LocalPolicyInput) -> tuple[PolicyEvaluation, SimulationReceipt | None]:
    reasons = [_quality_reason(flag) for flag in policy_input.quality.flags]
    patch_hash: Sha256Hex | None = None
    simulation_hash: Sha256Hex | None = None
    receipt: SimulationReceipt | None = None
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
                receipt = receipt_result
                patch_hash = receipt.evidence.patch_hash
                simulation_hash = receipt.evidence.simulation_hash
            case _:
                assert_never(receipt_result)
    frozen_reasons = tuple(reasons)
    body = _PolicyEvaluationBody(
        eligible=not frozen_reasons,
        reasons=frozen_reasons,
        patch_hash=patch_hash,
        simulation_hash=simulation_hash,
        policy_definition_hash=LOCAL_POLICY_DEFINITION_HASH,
    )
    return _build_evaluation(body), receipt


def evaluate_local_policy(policy_input: LocalPolicyInput) -> PolicyDecision:
    """Recompute simulator provenance and issue an internal capability."""
    evidence, receipt = _evaluate(policy_input)
    payload = PolicyDecisionPayload(
        quality=policy_input.quality,
        receipt=receipt,
        evidence=evidence,
    )
    return PolicyDecision(_DECISION_ISSUER, payload)


def revalidate_policy_decision(decision: PolicyDecision) -> PolicyVerification:
    """Re-resolve run, comparison, definition, and serialized evidence."""
    receipt = decision.receipt
    if receipt is None:
        return PolicyDecisionRejected(PolicyVerificationCode.PROVENANCE_REQUIRED)
    receipt_result = revalidate_counterfactual_receipt(receipt)
    match receipt_result:
        case ReceiptRejected():
            return PolicyDecisionRejected(PolicyVerificationCode.EVIDENCE_CHANGED)
        case SimulationReceipt():
            context = LocalPolicyInput(
                quality=decision.quality,
                run=receipt_result.run,
                comparison=receipt_result.comparison,
            )
        case _:
            assert_never(receipt_result)
    evidence, refreshed_receipt = _evaluate(context)
    if refreshed_receipt is None or evidence != decision.evidence:
        return PolicyDecisionRejected(PolicyVerificationCode.EVIDENCE_CHANGED)
    return evidence
