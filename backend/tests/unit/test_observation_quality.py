from __future__ import annotations

from pathlib import Path
from typing import Final

import pytest
from pydantic import ValidationError

from telco_twin.simulator.metrics import (
    ObservationQualityFlag,
    QualityAssessment,
    QualityContext,
    QualityPolicy,
    assess_observation_quality,
)
from telco_twin.simulator.network_model import NetworkObservation, load_scenario_manifests

SCENARIO_FIXTURES: Final = Path(__file__).parents[2] / "fixtures/scenarios"


def _radio_observation() -> NetworkObservation:
    manifests = load_scenario_manifests(SCENARIO_FIXTURES)
    return manifests[0].observation


def test_quality_threshold_boundaries_remain_approval_eligible() -> None:
    policy = QualityPolicy(
        max_age_seconds=120,
        max_prb_spread_pct=25.0,
        max_sinr_spread_db=8.0,
        max_latency_spread_ms=50.0,
    )
    observation = _radio_observation()
    first = observation.windows[0].model_copy(
        update={
            "observed_at": "2026-08-27T00:00:00Z",
            "prb_utilization_pct": 50.0,
            "sinr_db": 10.0,
            "latency_ms": 20.0,
        }
    )
    second = first.model_copy(
        update={
            "observed_at": "2026-08-27T00:02:00Z",
            "prb_utilization_pct": 75.0,
            "sinr_db": 18.0,
            "latency_ms": 70.0,
        }
    )
    context = QualityContext(assessed_at="2026-08-27T00:02:00Z", policy=policy)

    result = assess_observation_quality(
        observation.model_copy(update={"windows": (first, second)}),
        context,
    )

    assert result.flags == ()
    assert result.approval_eligible is True


def test_observation_just_past_maximum_age_is_stale_and_ineligible() -> None:
    observation = _radio_observation()
    window = observation.windows[0].model_copy(update={"observed_at": "2026-08-27T00:00:00Z"})
    context = QualityContext(
        assessed_at="2026-08-27T00:02:01Z",
        policy=QualityPolicy(max_age_seconds=120),
    )

    result = assess_observation_quality(
        observation.model_copy(update={"windows": (window,)}), context
    )

    assert result.flags == (ObservationQualityFlag.STALE,)
    assert result.approval_eligible is False


@pytest.mark.parametrize(
    ("field", "spread"),
    [
        ("prb_utilization_pct", 25.001),
        ("sinr_db", 8.001),
        ("latency_ms", 50.001),
    ],
)
def test_observation_just_past_noise_threshold_is_noisy_and_ineligible(
    field: str,
    spread: float,
) -> None:
    observation = _radio_observation()
    first = observation.windows[0].model_copy(
        update={
            "observed_at": "2026-08-27T00:01:00Z",
            "prb_utilization_pct": 40.0,
            "sinr_db": 10.0,
            "latency_ms": 10.0,
        }
    )
    second = first.model_copy(
        update={"observed_at": "2026-08-27T00:01:01Z", field: getattr(first, field) + spread}
    )
    context = QualityContext(assessed_at="2026-08-27T00:01:01Z")

    result = assess_observation_quality(
        observation.model_copy(update={"windows": (first, second)}),
        context,
    )

    assert result.flags == (ObservationQualityFlag.NOISY,)
    assert result.approval_eligible is False


def test_stale_and_noisy_flags_have_stable_order() -> None:
    observation = _radio_observation()
    first = observation.windows[0].model_copy(
        update={"observed_at": "2026-08-27T00:00:00Z", "prb_utilization_pct": 40.0}
    )
    second = first.model_copy(
        update={"observed_at": "2026-08-27T00:00:01Z", "prb_utilization_pct": 80.0}
    )
    context = QualityContext(assessed_at="2026-08-27T00:05:00Z")

    result = assess_observation_quality(
        observation.model_copy(update={"windows": (first, second)}),
        context,
    )

    assert result.flags == (ObservationQualityFlag.STALE, ObservationQualityFlag.NOISY)
    assert result.approval_eligible is False


def test_quality_flags_cannot_be_constructed_as_approval_eligible() -> None:
    with pytest.raises(ValidationError, match="quality_eligibility"):
        _ = QualityAssessment(
            flags=(ObservationQualityFlag.STALE,),
            approval_eligible=True,
        )


def test_spatial_heterogeneity_between_targets_is_not_temporal_noise() -> None:
    observation = _radio_observation()
    first = observation.windows[0].model_copy(
        update={"target_id": "cell-0001", "prb_utilization_pct": 20.0}
    )
    second = first.model_copy(update={"target_id": "cell-0002", "prb_utilization_pct": 60.0})

    result = assess_observation_quality(
        observation.model_copy(update={"windows": (first, second)}),
        QualityContext(assessed_at="2026-08-27T00:01:00Z"),
    )

    assert result.flags == ()
    assert result.approval_eligible is True


def test_repeated_same_target_variance_is_noisy() -> None:
    observation = _radio_observation()
    first = observation.windows[0].model_copy(update={"prb_utilization_pct": 20.0})
    second = first.model_copy(
        update={"observed_at": "2026-08-27T00:00:31Z", "prb_utilization_pct": 60.0}
    )

    result = assess_observation_quality(
        observation.model_copy(update={"windows": (first, second)}),
        QualityContext(assessed_at="2026-08-27T00:01:00Z"),
    )

    assert result.flags == (ObservationQualityFlag.NOISY,)
    assert result.approval_eligible is False
