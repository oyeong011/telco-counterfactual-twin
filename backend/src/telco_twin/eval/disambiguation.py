"""Counterfactual disambiguation: pick the fault that best reproduces the whole observation.

The closed rules can only threshold-test, so overlapping or sub-threshold evidence
forces them to abstain. The twin instead simulates each candidate family alone and
keeps the hypothesis whose synthesized observation sits nearest the real one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from telco_twin.domain.scenario import FaultFamily
from telco_twin.eval.rules_baseline import (
    DiagnosisCase,
    DiagnosisPrediction,
    PredictionStatus,
    predict_rules,
)
from telco_twin.simulator.metric_model import ObservationIdentity, synthesize_at_intensity
from telco_twin.simulator.metrics import QualityContext, assess_observation_quality
from telco_twin.simulator.network_model import AlarmKind, NetworkObservation

_FLAG_WEIGHT: Final = 1.5
_SLICE_LATENCY_SCALE: Final = 3.0
# The twin does not hold one template per family. It fits the intensity that
# best reproduces the observation, so a fault driven at 0.8 is compared against
# its own family at 0.8, not against a fixed dominant signature.
_INTENSITY_GRID: Final = tuple(i / 20 for i in range(1, 21))


@dataclass(frozen=True, slots=True)
class DisambiguationEvidence:
    """One prediction plus the hypotheses the twin actually simulated."""

    prediction: DiagnosisPrediction
    simulated_families: tuple[FaultFamily, ...]
    distances: tuple[tuple[FaultFamily, float], ...]


def _features(observation: NetworkObservation) -> tuple[float, ...]:
    window = observation.windows[0]
    config = observation.config_history[0]
    attempts = max(window.handover_attempts, 1)
    return (
        window.prb_utilization_pct / 100.0,
        window.active_ues / 500.0,
        window.throughput_mbps / 1000.0,
        window.latency_ms / 300.0,
        window.packet_loss_pct / 20.0,
        window.handover_failures / attempts,
        window.nf_cpu_utilization_pct / 100.0,
        window.slice_throughput_mbps / window.slice_slo_throughput_mbps,
        window.slice_latency_ms / window.slice_slo_latency_ms / _SLICE_LATENCY_SCALE,
        config.slice_scheduler_share_pct / config.expected_slice_share_pct,
        (0.0 if config.neighbor_relation_valid else 1.0) * _FLAG_WEIGHT,
        _injection_flag(observation) * _FLAG_WEIGHT,
    )


def _injection_flag(observation: NetworkObservation) -> float:
    return (
        1.0
        if any(alarm.kind is AlarmKind.PROMPT_INJECTION for alarm in observation.alarms)
        else 0.0
    )


def _distance(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    return sum(abs(a - b) for a, b in zip(left, right, strict=True))


def _hypothesis(family: FaultFamily, intensity: float, case: DiagnosisCase) -> NetworkObservation:
    return synthesize_at_intensity(
        ((family, intensity),),
        ObservationIdentity(
            case_slug=f"hypothesis-{family.value}",
            scenario_id=case.observation.scenario_id,
            topology_id=case.observation.topology_id,
        ),
    )


def fit_family(case: DiagnosisCase, family: FaultFamily) -> tuple[float, float]:
    """The intensity of one family that best reproduces the observation, and its distance."""
    observed = _features(case.observation)
    grid = (1.0,) if family is FaultFamily.ALARM_PROMPT_INJECTION else _INTENSITY_GRID
    best = min(
        ((_distance(observed, _features(_hypothesis(family, i, case))), i) for i in grid),
        key=lambda pair: (pair[0], pair[1]),
    )
    return best[1], best[0]


def rank_hypotheses(case: DiagnosisCase) -> tuple[tuple[FaultFamily, float], ...]:
    """Fit every family alone and rank them by the distance at their best intensity."""
    scored = tuple((family, fit_family(case, family)[1]) for family in FaultFamily)
    return tuple(sorted(scored, key=lambda item: (item[1], item[0].value)))


def explain_disambiguation(case: DiagnosisCase) -> DisambiguationEvidence:
    """Keep the rules answer when it concludes; otherwise resolve by simulation."""
    quality = assess_observation_quality(
        case.observation,
        QualityContext(assessed_at=case.assessed_at),
    )
    if not quality.approval_eligible:
        return DisambiguationEvidence(
            prediction=DiagnosisPrediction(
                case_id=case.case_id,
                status=PredictionStatus.ABSTAINED,
                label=None,
                quality_flags=quality.flags,
                schema_version="1.0",
            ),
            simulated_families=(),
            distances=(),
        )
    rules = predict_rules(case)
    if rules.status is PredictionStatus.PREDICTED and rules.label is not None:
        return DisambiguationEvidence(
            prediction=rules,
            simulated_families=(rules.label,),
            distances=(),
        )
    ranked = rank_hypotheses(case)
    return DisambiguationEvidence(
        prediction=DiagnosisPrediction(
            case_id=case.case_id,
            status=PredictionStatus.PREDICTED,
            label=ranked[0][0],
            quality_flags=quality.flags,
            schema_version="1.0",
        ),
        simulated_families=tuple(family for family, _ in ranked),
        distances=ranked,
    )


def predict_disambiguated(case: DiagnosisCase) -> DiagnosisPrediction:
    """Return only the prediction of the simulation-backed twin arm."""
    return explain_disambiguation(case).prediction
