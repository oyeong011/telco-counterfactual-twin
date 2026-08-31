"""Project a remediation patch's effect before approving it.

The shipped local checks are exact and binary: a parameter is inside its range,
a blast radius counts under its declared maximum, a hash matches. None of them
can see a patch that satisfies every bound and still pushes an unrelated metric
past its SLO, so a gate built only from them cannot be scored for judgment.

This module adds the missing dimension by projecting the patched observation
through the simulator's forward model and asking two questions the bounds cannot:
did the fault actually clear, and did anything else break.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum, unique
from typing import Final

CAPACITY_LOWER: Final = 1
CAPACITY_UPPER: Final = 1000

# Radio congestion clears once utilization falls back under its onset threshold.
PRB_FAULT_THRESHOLD_PCT: Final = 90.0
# Serving more UE slots costs core processing; past this the UPF breaches its SLO.
NF_CPU_SLO_PCT: Final = 90.0
CPU_COST_PER_UE_SLOT: Final = 0.225


@unique
class GateKind(StrEnum):
    """Which safety gate is deciding."""

    BOUNDS_ONLY = "bounds-only"
    SLO_PROJECTION = "slo-projection"


@unique
class BreachCode(StrEnum):
    """Closed set of reasons a projected patch is refused."""

    PARAMETER_RANGE = "patch-parameter-range"
    UPF_CPU_SLO = "upf-cpu-slo-exceeded"


@dataclass(frozen=True, slots=True)
class RemediationCase:
    """One proposed capacity change against one observed cell."""

    case_id: str
    baseline_capacity_ues: int
    patched_capacity_ues: int
    observed_prb_pct: float
    observed_nf_cpu_pct: float


@dataclass(frozen=True, slots=True)
class ProjectedOutcome:
    """The forward model's view of the network after the patch."""

    prb_after_pct: float
    nf_cpu_after_pct: float
    fault_cleared: bool
    breaches: tuple[BreachCode, ...]


@dataclass(frozen=True, slots=True)
class PatchDecision:
    """What one gate concluded about one case."""

    case_id: str
    gate: GateKind
    blocked: bool
    fault_cleared: bool
    breaches: tuple[BreachCode, ...]


def project_patch(case: RemediationCase) -> ProjectedOutcome:
    """Model added radio capacity relieving utilization while loading the core."""
    ratio = case.baseline_capacity_ues / case.patched_capacity_ues
    prb_after = min(100.0, case.observed_prb_pct * ratio)
    added_slots = case.patched_capacity_ues - case.baseline_capacity_ues
    nf_cpu_after = case.observed_nf_cpu_pct + CPU_COST_PER_UE_SLOT * added_slots
    breaches: list[BreachCode] = []
    if not CAPACITY_LOWER <= case.patched_capacity_ues <= CAPACITY_UPPER:
        breaches.append(BreachCode.PARAMETER_RANGE)
    if nf_cpu_after > NF_CPU_SLO_PCT:
        breaches.append(BreachCode.UPF_CPU_SLO)
    return ProjectedOutcome(
        prb_after_pct=prb_after,
        nf_cpu_after_pct=nf_cpu_after,
        fault_cleared=prb_after < PRB_FAULT_THRESHOLD_PCT,
        breaches=tuple(breaches),
    )


def decide_patch(case: RemediationCase, gate: GateKind) -> PatchDecision:
    """Block on the bounds alone, or on the bounds plus the projected outcome."""
    outcome = project_patch(case)
    breaches: tuple[BreachCode, ...]
    match gate:
        case GateKind.BOUNDS_ONLY:
            breaches = tuple(
                code for code in outcome.breaches if code is BreachCode.PARAMETER_RANGE
            )
        case GateKind.SLO_PROJECTION:
            breaches = outcome.breaches
    return PatchDecision(
        case_id=case.case_id,
        gate=gate,
        blocked=bool(breaches),
        fault_cleared=outcome.fault_cleared,
        breaches=breaches,
    )
