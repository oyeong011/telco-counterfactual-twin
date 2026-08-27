from __future__ import annotations

from pathlib import Path
from typing import Final

from telco_twin.simulator.metrics import (
    ObservationQualityFlag,
    QualityContext,
    assess_observation_quality,
)
from telco_twin.simulator.network_model import load_scenario_manifests

SCENARIO_FIXTURES: Final = Path(__file__).parents[2] / "fixtures/scenarios"


def test_future_metric_is_fail_closed_with_typed_future_flag() -> None:
    observation = load_scenario_manifests(SCENARIO_FIXTURES)[0].observation
    window = observation.windows[0].model_copy(update={"observed_at": "2026-08-27T00:02:00Z"})

    result = assess_observation_quality(
        observation.model_copy(update={"windows": (window,)}),
        QualityContext(assessed_at="2026-08-27T00:01:59Z"),
    )

    assert result.flags == (ObservationQualityFlag.FUTURE,)
    assert result.approval_eligible is False


def test_future_alarm_is_flagged_and_blocks_approval() -> None:
    prompt = load_scenario_manifests(SCENARIO_FIXTURES)[-1].observation
    future_alarm = prompt.alarms[0].model_copy(update={"observed_at": "2099-01-01T00:00:00Z"})

    result = assess_observation_quality(
        prompt.model_copy(update={"alarms": (future_alarm,)}),
        QualityContext(assessed_at="2026-08-27T00:01:00Z"),
    )

    assert result.flags == (ObservationQualityFlag.FUTURE,)
    assert result.approval_eligible is False


def test_stale_alarm_remains_diagnosable_but_blocks_approval() -> None:
    prompt = load_scenario_manifests(SCENARIO_FIXTURES)[-1].observation
    fresh_window = prompt.windows[0].model_copy(update={"observed_at": "2026-08-27T00:04:30Z"})
    stale_alarm = prompt.alarms[0].model_copy(update={"observed_at": "2026-08-27T00:00:00Z"})
    fresh_config = prompt.config_history[0].model_copy(
        update={"recorded_at": "2026-08-27T00:04:00Z"}
    )
    observation = prompt.model_copy(
        update={
            "windows": (fresh_window,),
            "alarms": (stale_alarm,),
            "config_history": (fresh_config,),
        }
    )

    result = assess_observation_quality(
        observation,
        QualityContext(assessed_at="2026-08-27T00:05:00Z"),
    )

    assert result.flags == (ObservationQualityFlag.STALE,)
    assert result.approval_eligible is False


def test_future_config_is_flagged_and_blocks_approval() -> None:
    neighbor = load_scenario_manifests(SCENARIO_FIXTURES)[3].observation
    future_config = neighbor.config_history[0].model_copy(
        update={"recorded_at": "2099-01-01T00:00:00Z"}
    )

    result = assess_observation_quality(
        neighbor.model_copy(update={"config_history": (future_config,)}),
        QualityContext(assessed_at="2026-08-27T00:01:00Z"),
    )

    assert result.flags == (ObservationQualityFlag.FUTURE,)
    assert result.approval_eligible is False


def test_stale_config_blocks_approval() -> None:
    neighbor = load_scenario_manifests(SCENARIO_FIXTURES)[3].observation
    fresh_window = neighbor.windows[0].model_copy(update={"observed_at": "2026-08-27T00:04:30Z"})
    stale_config = neighbor.config_history[0].model_copy(
        update={"recorded_at": "2026-08-27T00:00:00Z"}
    )
    observation = neighbor.model_copy(
        update={"windows": (fresh_window,), "config_history": (stale_config,)}
    )

    result = assess_observation_quality(
        observation,
        QualityContext(assessed_at="2026-08-27T00:05:00Z"),
    )

    assert result.flags == (ObservationQualityFlag.STALE,)
    assert result.approval_eligible is False
