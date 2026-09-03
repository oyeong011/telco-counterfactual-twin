"""Difficulty-tiered safety corpus.

The v1 safety fixture pairs every unsafe expectation with an exactly decidable
violation, so any correct gate sweeps it 20/20 and 0/20. Those numbers restate
the checks rather than measure them.

Here the expectation comes from the noiseless truth while the gate only ever
sees a noisy observation, so cases sitting near the SLO edge are genuinely
undecidable from a point estimate and a deterministic gate must err on one side.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum, unique
from typing import Annotated, Final

from pydantic import Field

from telco_twin.domain._contract import StrictContract
from telco_twin.safety.slo_projection import (
    GateKind,
    RemediationCase,
    decide_patch,
    project_patch,
)

BASELINE_CAPACITY_UES: Final = 200
TRUE_PRB_PCT: Final = 99.0
TRUE_NF_CPU_PCT: Final = 45.0
NOISE_FRACTION: Final = 0.12
INSTANCES_PER_TIER: Final = 4


@unique
class SafetyTier(StrEnum):
    """How close one proposed patch sits to the SLO edge."""

    CLEAR_SAFE = "clear-safe"
    BOUNDARY_SAFE = "boundary-safe"
    BOUNDARY_UNSAFE = "boundary-unsafe"
    CLEAR_UNSAFE = "clear-unsafe"
    INEFFECTIVE = "ineffective"


# Patched capacity per tier. 250 relieves the cell cheaply; 395 and 405 straddle
# the UPF CPU SLO; 600 breaches it outright; 210 is too small to clear the fault.
_TIER_CAPACITY: Final[dict[SafetyTier, int]] = {
    SafetyTier.CLEAR_SAFE: 250,
    SafetyTier.BOUNDARY_SAFE: 395,
    SafetyTier.BOUNDARY_UNSAFE: 405,
    SafetyTier.CLEAR_UNSAFE: 600,
    SafetyTier.INEFFECTIVE: 210,
}


@dataclass(frozen=True, slots=True)
class SafetyItem:
    """One case, the tier it came from, and the truth the gate is scored against."""

    case: RemediationCase
    tier: SafetyTier
    expected_unsafe: bool


class SafetyGateMetrics(StrictContract):
    """Independent block and false-block denominators for one gate."""

    gate: GateKind
    unsafe_blocked: Annotated[int, Field(ge=0)]
    unsafe_denominator: Annotated[int, Field(ge=0)]
    safe_false_blocks: Annotated[int, Field(ge=0)]
    safe_denominator: Annotated[int, Field(ge=0)]


def tier_capacity(tier: SafetyTier) -> int:
    """Expose the patched capacity one tier proposes."""
    return _TIER_CAPACITY[tier]


def truth_case(capacity: int) -> RemediationCase:
    """The noiseless case the expectation is derived from; no gate observes it."""
    return RemediationCase(
        case_id="truth",
        baseline_capacity_ues=BASELINE_CAPACITY_UES,
        patched_capacity_ues=capacity,
        observed_prb_pct=TRUE_PRB_PCT,
        observed_nf_cpu_pct=TRUE_NF_CPU_PCT,
    )


def _truth_is_unsafe(capacity: int) -> bool:
    return bool(project_patch(truth_case(capacity)).breaches)


def _observed(slug: str, index: int) -> tuple[float, float]:
    """Draw the noisy observation the gate is allowed to see."""
    digest = hashlib.sha256(f"safety:{slug}:{index}".encode()).digest()
    prb_scale = 1.0 + NOISE_FRACTION * ((digest[0] % 201) - 100) / 100.0
    cpu_scale = 1.0 + NOISE_FRACTION * ((digest[1] % 201) - 100) / 100.0
    return min(100.0, TRUE_PRB_PCT * prb_scale), min(100.0, TRUE_NF_CPU_PCT * cpu_scale)


def generate_safety_corpus_v2() -> tuple[SafetyItem, ...]:
    """Build every tier at a fixed number of independent noise draws."""
    items: list[SafetyItem] = []
    for tier, capacity in _TIER_CAPACITY.items():
        expected_unsafe = _truth_is_unsafe(capacity)
        for index in range(1, INSTANCES_PER_TIER + 1):
            observed_prb, observed_cpu = _observed(tier.value, index)
            items.append(
                SafetyItem(
                    case=RemediationCase(
                        case_id=f"safety-v2-{tier.value}-{index:02d}",
                        baseline_capacity_ues=BASELINE_CAPACITY_UES,
                        patched_capacity_ues=capacity,
                        observed_prb_pct=observed_prb,
                        observed_nf_cpu_pct=observed_cpu,
                    ),
                    tier=tier,
                    expected_unsafe=expected_unsafe,
                )
            )
    return tuple(items)


def score_safety_gate(items: tuple[SafetyItem, ...], gate: GateKind) -> SafetyGateMetrics:
    """Score one gate against the noiseless truth it never observes."""
    decisions = tuple((item, decide_patch(item.case, gate)) for item in items)
    unsafe = tuple(pair for pair in decisions if pair[0].expected_unsafe)
    safe = tuple(pair for pair in decisions if not pair[0].expected_unsafe)
    return SafetyGateMetrics(
        gate=gate,
        unsafe_blocked=sum(decision.blocked for _, decision in unsafe),
        unsafe_denominator=len(unsafe),
        safe_false_blocks=sum(decision.blocked for _, decision in safe),
        safe_denominator=len(safe),
    )
