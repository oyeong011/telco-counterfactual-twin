from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Final

import pytest
from pydantic import ValidationError

from telco_twin.domain.scenario import Scenario
from telco_twin.simulator.metrics import (
    ObservationQualityFlag,
    QualityAssessment,
    QualityContext,
    QualityPolicy,
    assess_observation_quality,
)
from telco_twin.simulator.network_model import NetworkObservation, load_scenario_manifests

if TYPE_CHECKING:
    from collections.abc import Iterator

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


def test_future_metric_is_fail_closed_with_typed_future_flag() -> None:
    observation = _radio_observation()
    window = observation.windows[0].model_copy(update={"observed_at": "2026-08-27T00:02:00Z"})
    context = QualityContext(assessed_at="2026-08-27T00:01:59Z")

    result = assess_observation_quality(
        observation.model_copy(update={"windows": (window,)}), context
    )

    assert result.flags == (ObservationQualityFlag.FUTURE,)
    assert result.approval_eligible is False


def test_empty_quality_window_is_rejected_instead_of_imputed() -> None:
    observation = _radio_observation()

    with pytest.raises(ValidationError, match="too_short"):
        _ = NetworkObservation(
            scenario_id=observation.scenario_id,
            topology_id=observation.topology_id,
            windows=(),
            alarms=observation.alarms,
            config_history=observation.config_history,
        )


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


def test_scenario_manifest_rejects_empty_declared_targets() -> None:
    manifest = load_scenario_manifests(SCENARIO_FIXTURES)[0]

    with pytest.raises(ValidationError, match="too_short"):
        _ = Scenario.model_validate({**manifest.scenario.model_dump(mode="json"), "target_ids": []})


def test_manifest_loading_order_ignores_permuted_directory_iteration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifests = load_scenario_manifests(SCENARIO_FIXTURES)
    radio = manifests[0]
    backhaul = manifests[1]
    _ = (tmp_path / "02-backhaul.json").write_text(backhaul.model_dump_json(), encoding="utf-8")
    _ = (tmp_path / "01-radio.json").write_text(radio.model_dump_json(), encoding="utf-8")
    real_glob = Path.glob

    def permuted_glob(directory: Path, pattern: str) -> Iterator[Path]:
        matches = tuple(real_glob(directory, pattern))
        if directory == tmp_path:
            return iter(reversed(matches))
        return iter(matches)

    monkeypatch.setattr(Path, "glob", permuted_glob)

    loaded = load_scenario_manifests(tmp_path)

    assert tuple(item.scenario.scenario_id for item in loaded) == (
        radio.scenario.scenario_id,
        backhaul.scenario.scenario_id,
    )
