"""Project a remediation patch's effect before approving it.

The shipped local checks are exact and binary: a parameter is inside its range,
a blast radius counts under its declared maximum, a hash matches. None of them
can see a patch that satisfies every bound and still pushes an unrelated metric
past its SLO, so a gate built only from them cannot be scored for judgment.

This module adds the missing dimension by projecting the patched observation
through a forward model and asking two questions the bounds cannot: did the
fault actually clear, and did anything else break.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum, unique
from typing import TYPE_CHECKING

from telco_twin.safety.remediation_models import (
    PARAMETER_RANGE,
    BreachCode,
    ObservedCell,
    project,
)

if TYPE_CHECKING:
    from telco_twin.domain.intervention import PatchOperation

__all__ = [
    "BreachCode",
    "GateKind",
    "ObservedCell",
    "PatchDecision",
    "ProjectedOutcome",
    "RemediationCase",
    "decide_patch",
    "project_patch",
]


@unique
class GateKind(StrEnum):
    """Which safety gate is deciding."""

    BOUNDS_ONLY = "bounds-only"
    SLO_PROJECTION = "slo-projection"


@dataclass(frozen=True, slots=True)
class RemediationCase:
    """One proposed sized change against one observed cell."""

    case_id: str
    operation: PatchOperation
    baseline_value: float
    patched_value: float
    observed: ObservedCell


@dataclass(frozen=True, slots=True)
class ProjectedOutcome:
    """The forward model's view of the network after the patch."""

    fault_cleared: bool
    projected: tuple[tuple[str, float], ...]
    breaches: tuple[BreachCode, ...]


@dataclass(frozen=True, slots=True)
class PatchDecision:
    """What one gate concluded about one case, and the numbers it concluded from."""

    case_id: str
    gate: GateKind
    blocked: bool
    fault_cleared: bool
    breaches: tuple[BreachCode, ...]
    projected: tuple[tuple[str, float], ...]


def _in_range(case: RemediationCase) -> bool:
    lower, upper = PARAMETER_RANGE[case.operation]
    return lower <= case.patched_value <= upper


def project_patch(case: RemediationCase) -> ProjectedOutcome:
    """Run the operation's model and collect every breach, bounds included."""
    projection = project(case.operation, case.observed, case.baseline_value, case.patched_value)
    breaches: list[BreachCode] = []
    if not _in_range(case):
        breaches.append(BreachCode.PARAMETER_RANGE)
    if projection.collateral is not None:
        breaches.append(projection.collateral)
    return ProjectedOutcome(
        fault_cleared=projection.fault_cleared,
        projected=projection.projected,
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
        projected=outcome.projected,
    )
