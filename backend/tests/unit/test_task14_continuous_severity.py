"""Task 14: severity is a continuous intensity, and instances differ where the rules look."""

from __future__ import annotations

from typing import TYPE_CHECKING

from telco_twin.domain.scenario import FaultFamily
from telco_twin.eval.corpus_v2 import DifficultyTier, generate_corpus_v2
from telco_twin.eval.metrics import EvaluationSplit
from telco_twin.eval.disambiguation import predict_disambiguated, rank_hypotheses
from telco_twin.eval.rules_baseline import DiagnosisCase, predict_rules
from telco_twin.eval.scoring_v2 import score_corpus
from telco_twin.simulator.faults import DiagnosisStatus, diagnose_fault
from telco_twin.simulator.metric_model import (
    ObservationIdentity,
    Severity,
    intensity_for,
    synthesize_at_intensity,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from telco_twin.simulator.metric_values import MetricWindow
    from telco_twin.simulator.network_model import NetworkObservation

IDENTITY = ObservationIdentity(case_slug="t", scenario_id="scenario-fit")


def _observe(family: FaultFamily, intensity: float) -> NetworkObservation:
    return synthesize_at_intensity(((family, intensity),), IDENTITY)


def _window(family: FaultFamily, intensity: float) -> MetricWindow:
    return _observe(family, intensity).windows[0]


def test_each_family_curve_is_monotone_in_intensity() -> None:
    """Driving a fault harder must never make its defining channel look healthier."""
    probes: dict[FaultFamily, Callable[[MetricWindow], float]] = {
        FaultFamily.RADIO_CONGESTION: lambda w: w.prb_utilization_pct,
        FaultFamily.BACKHAUL_DEGRADATION: lambda w: w.packet_loss_pct,
        FaultFamily.UPF_SATURATION: lambda w: w.nf_cpu_utilization_pct,
        FaultFamily.NEIGHBOR_HANDOVER_MISCONFIGURATION: lambda w: float(w.handover_failures),
        FaultFamily.SLICE_SCHEDULER_MISALLOCATION: lambda w: w.slice_latency_ms,
    }
    for family, probe in probes.items():
        values = [probe(_window(family, i / 10)) for i in range(11)]
        assert values == sorted(values), f"{family.value}: {values}"


def test_rule_onset_sits_strictly_inside_the_intensity_range() -> None:
    """The threshold must be crossable from both sides, or near-miss tiers are meaningless."""
    for family in FaultFamily:
        if family is FaultFamily.ALARM_PROMPT_INJECTION:
            continue
        onset = intensity_for(family, Severity.SECONDARY)
        below = intensity_for(family, Severity.NEAR_MISS)
        assert 0.0 < below < onset < 1.0, family.value
        obs_on = _observe(family, onset)
        obs_off = _observe(family, below)
        assert diagnose_fault(obs_on).status is DiagnosisStatus.PRIMARY, family.value
        assert diagnose_fault(obs_off).status is DiagnosisStatus.NO_FAULT, family.value


def test_instances_in_one_cell_differ_in_rule_relevant_channels() -> None:
    """Variation must live where the rules and the twin look, not only in radio quality."""
    corpus = generate_corpus_v2(seed=20270827, noise_fraction=0.0)
    cell = [
        item
        for item in corpus
        if item.tier is DifficultyTier.CLEAN
        and item.case.fault_family is FaultFamily.RADIO_CONGESTION
        and item.split.value == "heldout"
    ]
    prbs = {item.case.observation.windows[0].prb_utilization_pct for item in cell}
    assert len(prbs) == len(cell) >= 3


def test_twin_fits_intensity_rather_than_matching_one_template() -> None:
    """A dominant fault at 0.8 must still be nearer its own family than any other."""
    for family in FaultFamily:
        if family is FaultFamily.ALARM_PROMPT_INJECTION:
            continue
        obs = _observe(family, 0.8)
        case = DiagnosisCase(
            case_id="diag-v2-fit",
            split=EvaluationSplit.HELDOUT,
            fault_family=family,
            assessed_at="2026-08-27T00:01:00Z",
            observation=obs,
            schema_version="1.0",
        )
        assert rank_hypotheses(case)[0][0] is family, family.value


def test_arms_still_separate_and_neither_saturates() -> None:
    corpus = generate_corpus_v2(seed=20270827)
    heldout = tuple(item for item in corpus if item.split.value == "heldout")
    rules = score_corpus(heldout, predict_rules)
    twin = score_corpus(heldout, predict_disambiguated)
    assert rules.macro_f1 < twin.macro_f1 < 1.0
    assert rules.abstained_count > 0
