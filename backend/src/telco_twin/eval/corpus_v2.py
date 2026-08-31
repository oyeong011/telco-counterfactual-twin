"""Difficulty-tiered v2 diagnosis corpus.

The v1 corpus is a frozen contract and is never mutated. v2 adds tiers that the
closed rules provably cannot resolve, so the rules and twin arms can separate.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum, unique
from typing import TYPE_CHECKING, Final

from telco_twin.domain.scenario import FaultFamily
from telco_twin.eval.metrics import EvaluationSplit
from telco_twin.eval.rules_baseline import DiagnosisCase
from telco_twin.simulator.metric_model import (
    FaultComponent,
    Severity,
    synthesize_observation,
)

if TYPE_CHECKING:
    from telco_twin.simulator.metric_values import MetricWindow

ASSESSED_AT: Final = "2026-08-27T00:01:00Z"
INSTANCES_PER_CELL: Final = 3

# Measurement noise the twin's idealized forward model does not reproduce. Without
# it the twin would invert exactly the generator that produced the case, and its
# score would measure self-consistency rather than diagnostic skill.
NOISE_FRACTION: Final = 0.12
_NOISY_FIELDS: Final = (
    "prb_utilization_pct",
    "throughput_mbps",
    "latency_ms",
    "packet_loss_pct",
    "nf_cpu_utilization_pct",
    "active_ues",
    "slice_throughput_mbps",
    "slice_latency_ms",
    "handover_failures",
)


@unique
class DifficultyTier(StrEnum):
    """How hard one case is for a threshold-only baseline."""

    CLEAN = "clean"
    NEAR_THRESHOLD = "near-threshold"
    MASKED = "masked"
    CONFOUNDED = "confounded"


# Which family is layered underneath a confounded case's primary fault. Each pair
# is chosen so both rule predicates fire and the closed rules must abstain.
_CONFOUNDER: Final[dict[FaultFamily, FaultFamily]] = {
    FaultFamily.RADIO_CONGESTION: FaultFamily.BACKHAUL_DEGRADATION,
    FaultFamily.BACKHAUL_DEGRADATION: FaultFamily.UPF_SATURATION,
    FaultFamily.UPF_SATURATION: FaultFamily.BACKHAUL_DEGRADATION,
    FaultFamily.NEIGHBOR_HANDOVER_MISCONFIGURATION: FaultFamily.RADIO_CONGESTION,
    FaultFamily.SLICE_SCHEDULER_MISALLOCATION: FaultFamily.RADIO_CONGESTION,
    FaultFamily.ALARM_PROMPT_INJECTION: FaultFamily.RADIO_CONGESTION,
}

_TIER_SEVERITY: Final[dict[DifficultyTier, Severity]] = {
    DifficultyTier.CLEAN: Severity.DOMINANT,
    DifficultyTier.NEAR_THRESHOLD: Severity.NEAR_MISS,
    DifficultyTier.MASKED: Severity.MASKED_MISS,
    DifficultyTier.CONFOUNDED: Severity.DOMINANT,
}


@dataclass(frozen=True, slots=True)
class CorpusItem:
    """One generated case with the tier and split it belongs to."""

    case: DiagnosisCase
    tier: DifficultyTier
    split: EvaluationSplit


def _jitter(slug: str, seed: int) -> dict[str, float]:
    """Vary only radio-quality channels no rule and no hypothesis feature reads."""
    digest = hashlib.sha256(f"{seed}:{slug}".encode()).digest()
    return {
        "sinr_db": 18.0 + (digest[0] % 31 - 15) / 10.0,
        "rsrp_dbm": -85.0 + (digest[1] % 61 - 30) / 10.0,
        "rsrq_db": -10.0 + (digest[2] % 21 - 10) / 10.0,
    }


def _noisy_window(
    window: MetricWindow, slug: str, seed: int, noise_fraction: float
) -> MetricWindow:
    """Perturb rule-relevant channels deterministically, then clamp to the contract."""
    digest = hashlib.sha256(f"noise:{seed}:{slug}".encode()).digest()
    current: dict[str, float | int] = {
        "prb_utilization_pct": window.prb_utilization_pct,
        "throughput_mbps": window.throughput_mbps,
        "latency_ms": window.latency_ms,
        "packet_loss_pct": window.packet_loss_pct,
        "nf_cpu_utilization_pct": window.nf_cpu_utilization_pct,
        "active_ues": window.active_ues,
        "slice_throughput_mbps": window.slice_throughput_mbps,
        "slice_latency_ms": window.slice_latency_ms,
        "handover_failures": window.handover_failures,
    }
    updates: dict[str, float | int] = {}
    for offset, field in enumerate(_NOISY_FIELDS):
        scale = 1.0 + noise_fraction * ((digest[offset] % 201) - 100) / 100.0
        value = current[field] * scale
        updates[field] = round(value) if isinstance(current[field], int) else value
    for percent_field in ("prb_utilization_pct", "nf_cpu_utilization_pct", "packet_loss_pct"):
        updates[percent_field] = min(100.0, float(updates[percent_field]))
    updates["handover_failures"] = min(int(updates["handover_failures"]), window.handover_attempts)
    return window.model_copy(update=updates)


def _components(family: FaultFamily, tier: DifficultyTier) -> tuple[FaultComponent, ...]:
    primary = FaultComponent(family=family, severity=_TIER_SEVERITY[tier])
    if tier is not DifficultyTier.CONFOUNDED:
        return (primary,)
    confounder = FaultComponent(family=_CONFOUNDER[family], severity=Severity.SECONDARY)
    return (confounder, primary)


def _case(
    family: FaultFamily,
    tier: DifficultyTier,
    split: EvaluationSplit,
    index: int,
    seed: int,
    noise_fraction: float,
) -> DiagnosisCase:
    slug = f"{split.value}-{tier.value}-{family.value}-{index:02d}"
    observation = synthesize_observation(
        _components(family, tier),
        case_slug=slug,
        scenario_id=f"scenario-v2-{slug}",
        jitter=_jitter(slug, seed),
    )
    observation = observation.model_copy(
        update={"windows": (_noisy_window(observation.windows[0], slug, seed, noise_fraction),)}
    )
    return DiagnosisCase(
        case_id=f"diag-v2-{slug}",
        split=split,
        fault_family=family,
        assessed_at=ASSESSED_AT,
        observation=observation,
        schema_version="1.0",
    )


def generate_corpus_v2(
    seed: int, *, noise_fraction: float = NOISE_FRACTION
) -> tuple[CorpusItem, ...]:
    """Build the full deterministic v2 corpus; pass 0.0 to ablate measurement noise."""
    return tuple(
        CorpusItem(
            case=_case(family, tier, split, index, seed, noise_fraction),
            tier=tier,
            split=split,
        )
        for split in EvaluationSplit
        for family in FaultFamily
        for tier in DifficultyTier
        for index in range(1, INSTANCES_PER_CELL + 1)
    )
