"""Difficulty-tiered safety corpus across every sized remediation.

The v1 safety fixture pairs every unsafe expectation with an exactly decidable
violation, so any correct gate sweeps it 20/20 and 0/20. Those numbers restate
the checks rather than measure them.

Here the expectation comes from the noiseless truth while the gate only ever
sees a noisy observation, so cases sitting near an SLO edge are genuinely
undecidable from a point estimate and a deterministic gate must err on one side.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from enum import StrEnum, unique
from typing import Annotated, Final

from pydantic import Field

from telco_twin.domain._contract import StrictContract
from telco_twin.domain.intervention import PatchOperation
from telco_twin.safety.slo_projection import (
    GateKind,
    ObservedCell,
    RemediationCase,
    decide_patch,
    project_patch,
)

NOISE_FRACTION: Final = 0.12
INSTANCES_PER_TIER: Final = 4

MODELED_OPERATIONS: Final = (
    PatchOperation.ADJUST_RADIO_CAPACITY,
    PatchOperation.RESTORE_BACKHAUL_CAPACITY,
    PatchOperation.SCALE_UPF_CAPACITY,
    PatchOperation.REBALANCE_SLICE_WEIGHT,
)


@unique
class SafetyTier(StrEnum):
    """How close one proposed patch sits to its SLO edge."""

    CLEAR_SAFE = "clear-safe"
    BOUNDARY_SAFE = "boundary-safe"
    BOUNDARY_UNSAFE = "boundary-unsafe"
    CLEAR_UNSAFE = "clear-unsafe"
    INEFFECTIVE = "ineffective"


_NOMINAL: Final = ObservedCell(
    prb_pct=55.0,
    nf_cpu_pct=45.0,
    packet_loss_pct=0.1,
    latency_ms=20.0,
    throughput_mbps=800.0,
    site_power_kw=6.0,
    slice_latency_ms=25.0,
    peer_slice_latency_ms=25.0,
)

# What the noiseless cell looks like when each fault is present. Noise is
# applied on top of this; the expectation is derived from it directly.
_TRUTH_OBSERVED: Final[dict[PatchOperation, ObservedCell]] = {
    PatchOperation.ADJUST_RADIO_CAPACITY: replace(_NOMINAL, prb_pct=99.0),
    PatchOperation.RESTORE_BACKHAUL_CAPACITY: replace(
        _NOMINAL, packet_loss_pct=12.0, latency_ms=220.0, throughput_mbps=300.0
    ),
    PatchOperation.SCALE_UPF_CAPACITY: replace(_NOMINAL, nf_cpu_pct=99.0),
    PatchOperation.REBALANCE_SLICE_WEIGHT: replace(
        _NOMINAL, slice_latency_ms=100.0, peer_slice_latency_ms=32.0
    ),
}

_BASELINE_VALUE: Final[dict[PatchOperation, float]] = {
    PatchOperation.ADJUST_RADIO_CAPACITY: 200,
    PatchOperation.RESTORE_BACKHAUL_CAPACITY: 400,
    PatchOperation.SCALE_UPF_CAPACITY: 5,
    PatchOperation.REBALANCE_SLICE_WEIGHT: 20,
}

# Patched value per operation and tier. Boundary pairs straddle the SLO that
# the operation's collateral coupling can breach; ineffective is too small, or
# for the UPF a reduction, to clear the fault at all.
_TIER_VALUE: Final[dict[PatchOperation, dict[SafetyTier, float]]] = {
    PatchOperation.ADJUST_RADIO_CAPACITY: {
        SafetyTier.CLEAR_SAFE: 250,
        SafetyTier.BOUNDARY_SAFE: 395,
        SafetyTier.BOUNDARY_UNSAFE: 405,
        SafetyTier.CLEAR_UNSAFE: 600,
        SafetyTier.INEFFECTIVE: 210,
    },
    PatchOperation.RESTORE_BACKHAUL_CAPACITY: {
        SafetyTier.CLEAR_SAFE: 700,
        SafetyTier.BOUNDARY_SAFE: 800,
        SafetyTier.BOUNDARY_UNSAFE: 810,
        SafetyTier.CLEAR_UNSAFE: 900,
        SafetyTier.INEFFECTIVE: 500,
    },
    PatchOperation.SCALE_UPF_CAPACITY: {
        SafetyTier.CLEAR_SAFE: 6,
        SafetyTier.BOUNDARY_SAFE: 8,
        SafetyTier.BOUNDARY_UNSAFE: 9,
        SafetyTier.CLEAR_UNSAFE: 12,
        SafetyTier.INEFFECTIVE: 4,
    },
    PatchOperation.REBALANCE_SLICE_WEIGHT: {
        SafetyTier.CLEAR_SAFE: 58,
        SafetyTier.BOUNDARY_SAFE: 75,
        SafetyTier.BOUNDARY_UNSAFE: 78,
        SafetyTier.CLEAR_UNSAFE: 100,
        SafetyTier.INEFFECTIVE: 40,
    },
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


def tier_value(operation: PatchOperation, tier: SafetyTier) -> float:
    """Expose the patched value one tier proposes for one operation."""
    return _TIER_VALUE[operation][tier]


def truth_case(operation: PatchOperation, patched_value: float) -> RemediationCase:
    """The noiseless case the expectation is derived from; no gate observes it."""
    return RemediationCase(
        case_id=f"truth-{operation.value}",
        operation=operation,
        baseline_value=_BASELINE_VALUE[operation],
        patched_value=patched_value,
        observed=_TRUTH_OBSERVED[operation],
    )


def _noisy(observed: ObservedCell, slug: str) -> ObservedCell:
    """Perturb every observed channel deterministically, then clamp percentages."""
    digest = hashlib.sha256(f"safety:{slug}".encode()).digest()
    channels: tuple[tuple[str, float], ...] = (
        ("prb_pct", observed.prb_pct),
        ("nf_cpu_pct", observed.nf_cpu_pct),
        ("packet_loss_pct", observed.packet_loss_pct),
        ("latency_ms", observed.latency_ms),
        ("throughput_mbps", observed.throughput_mbps),
        ("site_power_kw", observed.site_power_kw),
        ("slice_latency_ms", observed.slice_latency_ms),
        ("peer_slice_latency_ms", observed.peer_slice_latency_ms),
    )
    updates: dict[str, float] = {}
    for offset, (name, current) in enumerate(channels):
        scale = 1.0 + NOISE_FRACTION * ((digest[offset] % 201) - 100) / 100.0
        value = current * scale
        updates[name] = min(100.0, value) if name.endswith("_pct") else value
    return replace(observed, **updates)


def generate_safety_corpus_v2() -> tuple[SafetyItem, ...]:
    """Build every operation and tier at a fixed number of independent noise draws."""
    items: list[SafetyItem] = []
    for operation in MODELED_OPERATIONS:
        for tier in SafetyTier:
            patched = tier_value(operation, tier)
            expected_unsafe = bool(project_patch(truth_case(operation, patched)).breaches)
            for index in range(1, INSTANCES_PER_TIER + 1):
                slug = f"{operation.value}:{tier.value}:{index}"
                items.append(
                    SafetyItem(
                        case=RemediationCase(
                            case_id=f"safety-v2-{operation.value}-{tier.value}-{index:02d}",
                            operation=operation,
                            baseline_value=_BASELINE_VALUE[operation],
                            patched_value=patched,
                            observed=_noisy(_TRUTH_OBSERVED[operation], slug),
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
