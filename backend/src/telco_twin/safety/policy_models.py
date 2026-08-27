"""Local-policy evidence and sealed decision capability types."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum, unique
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, Self, final, override

from pydantic import model_validator

from telco_twin.domain._contract import Sha256Hex, StrictContract
from telco_twin.domain._validation import fail_validation
from telco_twin.domain.canonical import canonical_model_bytes
from telco_twin.simulator.metrics import ObservationQualityFlag

if TYPE_CHECKING:
    from telco_twin.counterfactual.receipt import SimulationReceipt
    from telco_twin.safety.quality_receipt import QualityReceipt


class _PolicyDefinition(StrictContract):
    policy_id: str
    version: str
    require_fresh_observation: bool
    require_all_constraints: bool
    require_simulator_receipt: bool
    require_quality_receipt: bool


POLICY_DEFINITION: Final = _PolicyDefinition(
    policy_id="c1-local-safety",
    version="1.2.0",
    require_fresh_observation=True,
    require_all_constraints=True,
    require_simulator_receipt=True,
    require_quality_receipt=True,
)
LOCAL_POLICY_DEFINITION_HASH: Final[Sha256Hex] = hashlib.sha256(
    canonical_model_bytes(POLICY_DEFINITION)
).hexdigest()


@unique
class PolicyReason(StrEnum):
    """Stable fail-closed local policy reasons."""

    OBSERVATION_STALE = "observation-stale"
    OBSERVATION_FUTURE = "observation-future"
    OBSERVATION_NOISY = "observation-noisy"
    OBSERVATION_BINDING = "observation-binding-invalid"
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


class PolicyEvaluation(StrictContract):
    """Serializable evidence that is insufficient without the internal capability."""

    eligible: bool
    reasons: tuple[PolicyReason, ...]
    patch_hash: Sha256Hex | None
    simulation_hash: Sha256Hex | None
    quality_hash: Sha256Hex
    policy_definition_hash: Sha256Hex
    policy_hash: Sha256Hex

    @model_validator(mode="after")
    def hash_and_eligibility_are_consistent(self) -> Self:
        """Reject altered evidence and success without exact simulator identities."""
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


POLICY_DECISION_ISSUER = PolicyDecisionIssuer()


@dataclass(frozen=True, slots=True)
class PolicyDecisionPayload:
    """Immutable evaluator inputs retained by the internal capability."""

    quality_receipt: QualityReceipt
    simulation_receipt: SimulationReceipt | None
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
        """Accept construction only from the local policy evaluator."""
        if issuer is not POLICY_DECISION_ISSUER:
            raise PolicyDecisionCreationError
        self._payload = payload

    @property
    def evidence(self) -> PolicyEvaluation:
        """Return the serializable evidence projection."""
        return self._payload.evidence

    @property
    def receipt(self) -> SimulationReceipt | None:
        """Return the retained simulator receipt."""
        return self._payload.simulation_receipt

    @property
    def quality_receipt(self) -> QualityReceipt:
        """Return retained observation-quality provenance."""
        return self._payload.quality_receipt


type PolicyAdmission = PolicyDecision | PolicyEvaluation


@unique
class PolicyVerificationCode(StrEnum):
    """Stable failures when approval re-resolves provenance."""

    PROVENANCE_REQUIRED = "policy-provenance-required"
    EVIDENCE_CHANGED = "policy-evidence-changed"
    QUALITY_CHANGED = "policy-quality-changed"


@dataclass(frozen=True, slots=True)
class PolicyDecisionRejected:
    """Fail-closed provenance revalidation result."""

    code: PolicyVerificationCode


type PolicyVerification = PolicyEvaluation | PolicyDecisionRejected
