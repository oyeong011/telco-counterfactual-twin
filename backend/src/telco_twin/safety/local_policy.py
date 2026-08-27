"""C1-local policy over typed quality, simulation, and hash evidence only."""

from __future__ import annotations

import hashlib
from enum import StrEnum, unique
from typing import Self, assert_never

from pydantic import model_validator

from telco_twin.counterfactual.comparison import (
    CounterfactualComparison,
    hash_comparison,
)
from telco_twin.domain._contract import Sha256Hex, StrictContract
from telco_twin.domain._validation import fail_validation
from telco_twin.domain.canonical import canonical_model_bytes
from telco_twin.simulator.metrics import ObservationQualityFlag, QualityAssessment


class _PolicyDefinition(StrictContract):
    """Canonical constants that identify the local safety policy."""

    policy_id: str
    version: str
    require_fresh_observation: bool
    require_all_constraints: bool
    require_exact_hash_bindings: bool


POLICY_DEFINITION = _PolicyDefinition(
    policy_id="c1-local-safety",
    version="1.0.0",
    require_fresh_observation=True,
    require_all_constraints=True,
    require_exact_hash_bindings=True,
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
    PATCH_HASH_CHANGED = "patch-hash-changed"
    SIMULATION_MISSING = "simulation-missing"
    SIMULATION_HASH_MISSING = "simulation-hash-missing"
    SIMULATION_HASH_CHANGED = "simulation-hash-changed"
    POLICY_HASH_MISSING = "policy-hash-missing"
    POLICY_HASH_CHANGED = "policy-hash-changed"


class _QualityFlagInput(StrictContract):
    flag: ObservationQualityFlag


class PolicyBindings(StrictContract):
    """Expected and observed evidence identities checked without inference."""

    expected_patch_hash: Sha256Hex
    observed_patch_hash: Sha256Hex | None
    expected_simulation_hash: Sha256Hex
    observed_simulation_hash: Sha256Hex | None
    expected_policy_definition_hash: Sha256Hex
    observed_policy_definition_hash: Sha256Hex | None


class LocalPolicyInput(StrictContract):
    """Complete machine-consumed local policy boundary; prose is absent."""

    quality: QualityAssessment
    comparison: CounterfactualComparison | None
    bindings: PolicyBindings


class PolicyEvaluationInput(StrictContract):
    """Complete evidence fields used to construct a hashed policy result."""

    eligible: bool
    reasons: tuple[PolicyReason, ...]
    patch_hash: Sha256Hex | None
    simulation_hash: Sha256Hex | None
    policy_definition_hash: Sha256Hex


class PolicyEvaluation(PolicyEvaluationInput):
    """Hashed policy result bound into every approval request."""

    policy_hash: Sha256Hex

    @model_validator(mode="after")
    def hash_and_eligibility_are_consistent(self) -> Self:
        """Reject altered policy results and success without complete evidence."""
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

    @classmethod
    def build(cls, body: PolicyEvaluationInput) -> Self:
        """Construct a self-hashed immutable policy result."""
        return cls(
            eligible=body.eligible,
            reasons=body.reasons,
            patch_hash=body.patch_hash,
            simulation_hash=body.simulation_hash,
            policy_definition_hash=body.policy_definition_hash,
            policy_hash=hashlib.sha256(canonical_model_bytes(body)).hexdigest(),
        )


def _quality_reason(quality: _QualityFlagInput) -> PolicyReason:
    match quality.flag:
        case ObservationQualityFlag.STALE:
            return PolicyReason.OBSERVATION_STALE
        case ObservationQualityFlag.FUTURE:
            return PolicyReason.OBSERVATION_FUTURE
        case ObservationQualityFlag.NOISY:
            return PolicyReason.OBSERVATION_NOISY
        case _:
            assert_never(quality.flag)


def _binding_reasons(policy_input: LocalPolicyInput) -> tuple[PolicyReason, ...]:
    bindings = policy_input.bindings
    reasons: list[PolicyReason] = []
    if bindings.observed_patch_hash is None:
        reasons.append(PolicyReason.PATCH_HASH_MISSING)
    elif bindings.observed_patch_hash != bindings.expected_patch_hash:
        reasons.append(PolicyReason.PATCH_HASH_CHANGED)
    if bindings.observed_simulation_hash is None:
        reasons.append(PolicyReason.SIMULATION_HASH_MISSING)
    elif bindings.observed_simulation_hash != bindings.expected_simulation_hash:
        reasons.append(PolicyReason.SIMULATION_HASH_CHANGED)
    if bindings.observed_policy_definition_hash is None:
        reasons.append(PolicyReason.POLICY_HASH_MISSING)
    elif (
        bindings.expected_policy_definition_hash != LOCAL_POLICY_DEFINITION_HASH
        or bindings.observed_policy_definition_hash != bindings.expected_policy_definition_hash
    ):
        reasons.append(PolicyReason.POLICY_HASH_CHANGED)
    return tuple(reasons)


def evaluate_local_policy(policy_input: LocalPolicyInput) -> PolicyEvaluation:
    """Evaluate typed evidence locally and fail closed on every missing binding."""
    reasons = [_quality_reason(_QualityFlagInput(flag=flag)) for flag in policy_input.quality.flags]
    reasons.extend(_binding_reasons(policy_input))
    comparison = policy_input.comparison
    if comparison is None:
        reasons.append(PolicyReason.SIMULATION_MISSING)
    else:
        if not comparison.result.approval_eligible or any(
            not constraint.passed for constraint in comparison.result.constraints
        ):
            reasons.append(PolicyReason.UNSAFE_CONSTRAINT)
        if (
            policy_input.bindings.observed_patch_hash is not None
            and policy_input.bindings.observed_patch_hash != comparison.result.patch_hash
            and PolicyReason.PATCH_HASH_CHANGED not in reasons
        ):
            reasons.append(PolicyReason.PATCH_HASH_CHANGED)
        if (
            policy_input.bindings.observed_simulation_hash is not None
            and policy_input.bindings.observed_simulation_hash != hash_comparison(comparison)
            and PolicyReason.SIMULATION_HASH_CHANGED not in reasons
        ):
            reasons.append(PolicyReason.SIMULATION_HASH_CHANGED)
    frozen_reasons = tuple(reasons)
    return PolicyEvaluation.build(
        PolicyEvaluationInput(
            eligible=not frozen_reasons,
            reasons=frozen_reasons,
            patch_hash=policy_input.bindings.observed_patch_hash,
            simulation_hash=policy_input.bindings.observed_simulation_hash,
            policy_definition_hash=LOCAL_POLICY_DEFINITION_HASH,
        )
    )
