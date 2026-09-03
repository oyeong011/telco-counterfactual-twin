"""Forward models for every sized remediation, each with the collateral cost the bounds cannot see.

A patch that is inside its parameter range, inside its blast radius, and
hash-consistent can still break something the shipped checks never look at.
Each model here names that something:

- adding radio capacity relieves the cell and loads the core;
- restoring backhaul lets more traffic through and loads the core;
- adding UPF units relieves the core and draws site power;
- raising one slice's weight relieves that slice and starves its peer.

The two boolean operations, correcting a neighbour relation and ignoring an
alarm, carry no magnitude and are not modeled here.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum, unique
from typing import Final, override

from telco_twin.domain.intervention import PatchOperation

PRB_FAULT_THRESHOLD_PCT: Final = 90.0
NF_CPU_SLO_PCT: Final = 90.0
BACKHAUL_LOSS_THRESHOLD_PCT: Final = 5.0
BACKHAUL_LATENCY_THRESHOLD_MS: Final = 100.0
SITE_POWER_BUDGET_KW: Final = 8.5
SLICE_LATENCY_SLO_MS: Final = 50.0

CPU_COST_PER_UE_SLOT: Final = 0.225
CPU_COST_PER_MBPS: Final = 0.09
BACKHAUL_OFFERED_MBPS: Final = 900.0
BACKHAUL_NOMINAL_LATENCY_MS: Final = 20.0
BACKHAUL_QUEUE_LATENCY_MS: Final = 200.0
BACKHAUL_NOMINAL_LOSS_PCT: Final = 0.1
BACKHAUL_CONGESTED_LOSS_PCT: Final = 12.0
POWER_KW_PER_UPF_UNIT: Final = 0.7
PEER_SLICE_WEIGHT: Final = 80.0

# Closed parameter ranges, mirrored from the patch specs the bounds gate enforces.
PARAMETER_RANGE: Final[dict[PatchOperation, tuple[float, float]]] = {
    PatchOperation.ADJUST_RADIO_CAPACITY: (1, 1000),
    PatchOperation.RESTORE_BACKHAUL_CAPACITY: (1, 1_000_000),
    PatchOperation.SCALE_UPF_CAPACITY: (1, 10_000),
    PatchOperation.REBALANCE_SLICE_WEIGHT: (1, 100),
}


@unique
class BreachCode(StrEnum):
    """Closed set of reasons a projected patch is refused."""

    PARAMETER_RANGE = "patch-parameter-range"
    UPF_CPU_SLO = "upf-cpu-slo-exceeded"
    SITE_POWER_BUDGET = "site-power-budget-exceeded"
    PEER_SLICE_LATENCY_SLO = "peer-slice-latency-slo-exceeded"


@dataclass(frozen=True, slots=True)
class ObservedCell:
    """What the gate is allowed to see before a patch: one noisy observation."""

    prb_pct: float
    nf_cpu_pct: float
    packet_loss_pct: float
    latency_ms: float
    throughput_mbps: float
    site_power_kw: float
    slice_latency_ms: float
    peer_slice_latency_ms: float


@dataclass(frozen=True, slots=True)
class Projection:
    """One model's view of the cell after the patch."""

    fault_cleared: bool
    projected: tuple[tuple[str, float], ...]
    collateral: BreachCode | None


@dataclass(frozen=True, slots=True)
class UnmodeledOperationError(Exception):
    """The operation carries no magnitude, so nothing here can project it."""

    operation: PatchOperation

    @override
    def __str__(self) -> str:
        return f"unmodeled-operation:{self.operation.value}"


def _radio(observed: ObservedCell, baseline: float, patched: float) -> Projection:
    prb_after = min(100.0, observed.prb_pct * baseline / patched)
    nf_cpu_after = observed.nf_cpu_pct + CPU_COST_PER_UE_SLOT * (patched - baseline)
    return Projection(
        fault_cleared=prb_after < PRB_FAULT_THRESHOLD_PCT,
        projected=(("prb_pct", prb_after), ("nf_cpu_pct", nf_cpu_after)),
        collateral=BreachCode.UPF_CPU_SLO if nf_cpu_after > NF_CPU_SLO_PCT else None,
    )


def _backhaul(observed: ObservedCell, baseline: float, patched: float) -> Projection:
    del baseline  # relief depends on the restored capacity against offered load
    throughput_after = min(BACKHAUL_OFFERED_MBPS, patched)
    shortfall = max(0.0, (BACKHAUL_OFFERED_MBPS - patched) / BACKHAUL_OFFERED_MBPS)
    loss_after = BACKHAUL_NOMINAL_LOSS_PCT + BACKHAUL_CONGESTED_LOSS_PCT * shortfall
    latency_after = BACKHAUL_NOMINAL_LATENCY_MS + BACKHAUL_QUEUE_LATENCY_MS * shortfall
    admitted = max(0.0, throughput_after - observed.throughput_mbps)
    nf_cpu_after = observed.nf_cpu_pct + CPU_COST_PER_MBPS * admitted
    return Projection(
        fault_cleared=(
            loss_after < BACKHAUL_LOSS_THRESHOLD_PCT
            and latency_after < BACKHAUL_LATENCY_THRESHOLD_MS
        ),
        projected=(
            ("packet_loss_pct", loss_after),
            ("latency_ms", latency_after),
            ("nf_cpu_pct", nf_cpu_after),
        ),
        collateral=BreachCode.UPF_CPU_SLO if nf_cpu_after > NF_CPU_SLO_PCT else None,
    )


def _upf(observed: ObservedCell, baseline: float, patched: float) -> Projection:
    nf_cpu_after = min(100.0, observed.nf_cpu_pct * baseline / patched)
    power_after = observed.site_power_kw + POWER_KW_PER_UPF_UNIT * (patched - baseline)
    return Projection(
        fault_cleared=nf_cpu_after < NF_CPU_SLO_PCT,
        projected=(("nf_cpu_pct", nf_cpu_after), ("site_power_kw", power_after)),
        collateral=BreachCode.SITE_POWER_BUDGET if power_after > SITE_POWER_BUDGET_KW else None,
    )


def _slice(observed: ObservedCell, baseline: float, patched: float) -> Projection:
    share_before = baseline / (baseline + PEER_SLICE_WEIGHT)
    share_after = patched / (patched + PEER_SLICE_WEIGHT)
    peer_before = PEER_SLICE_WEIGHT / (baseline + PEER_SLICE_WEIGHT)
    peer_after = PEER_SLICE_WEIGHT / (patched + PEER_SLICE_WEIGHT)
    slice_latency_after = observed.slice_latency_ms * share_before / share_after
    peer_latency_after = observed.peer_slice_latency_ms * peer_before / peer_after
    return Projection(
        fault_cleared=slice_latency_after < SLICE_LATENCY_SLO_MS,
        projected=(
            ("slice_latency_ms", slice_latency_after),
            ("peer_slice_latency_ms", peer_latency_after),
        ),
        collateral=(
            BreachCode.PEER_SLICE_LATENCY_SLO if peer_latency_after > SLICE_LATENCY_SLO_MS else None
        ),
    )


def project(
    operation: PatchOperation,
    observed: ObservedCell,
    baseline: float,
    patched: float,
) -> Projection:
    """Dispatch to the model for one sized operation."""
    match operation:
        case PatchOperation.ADJUST_RADIO_CAPACITY:
            return _radio(observed, baseline, patched)
        case PatchOperation.RESTORE_BACKHAUL_CAPACITY:
            return _backhaul(observed, baseline, patched)
        case PatchOperation.SCALE_UPF_CAPACITY:
            return _upf(observed, baseline, patched)
        case PatchOperation.REBALANCE_SLICE_WEIGHT:
            return _slice(observed, baseline, patched)
        case PatchOperation.CORRECT_NEIGHBOR_RELATION | PatchOperation.IGNORE_UNTRUSTED_ALARM:
            raise UnmodeledOperationError(operation)
