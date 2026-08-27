from __future__ import annotations

from pathlib import Path
from typing import Final

import pytest

from telco_twin.domain.scenario import FaultFamily
from telco_twin.simulator.faults import diagnose_fault
from telco_twin.simulator.network_model import (
    AlarmEvidence,
    AlarmKind,
    ScenarioManifest,
    load_scenario_manifests,
)

SCENARIO_FIXTURES: Final = Path(__file__).parents[2] / "fixtures/scenarios"


def _manifest(family: FaultFamily) -> ScenarioManifest:
    return next(
        item
        for item in load_scenario_manifests(SCENARIO_FIXTURES)
        if item.scenario.fault_family is family
    )


@pytest.mark.parametrize(
    ("updates", "expected_primary", "expected_status"),
    [
        (
            (("packet_loss_pct", 4.999), ("latency_ms", 100.0)),
            None,
            "no-fault",
        ),
        (
            (("packet_loss_pct", 5.0), ("latency_ms", 99.999)),
            None,
            "no-fault",
        ),
        (
            (("packet_loss_pct", 5.0), ("latency_ms", 100.0)),
            FaultFamily.BACKHAUL_DEGRADATION,
            "primary",
        ),
        (
            (("nf_cpu_utilization_pct", 89.999), ("latency_ms", 75.0)),
            None,
            "no-fault",
        ),
        (
            (("nf_cpu_utilization_pct", 90.0), ("latency_ms", 74.999)),
            None,
            "no-fault",
        ),
        (
            (("nf_cpu_utilization_pct", 90.0), ("latency_ms", 75.0)),
            FaultFamily.UPF_SATURATION,
            "primary",
        ),
    ],
)
def test_fault_thresholds_are_inclusive_only_at_complete_boundary(
    updates: tuple[tuple[str, float], ...],
    expected_primary: FaultFamily | None,
    expected_status: str,
) -> None:
    nominal = _manifest(FaultFamily.ALARM_PROMPT_INJECTION).observation.model_copy(
        update={"alarms": ()}
    )
    window = nominal.windows[0].model_copy(update=dict(updates))

    result = diagnose_fault(nominal.model_copy(update={"windows": (window,)}))

    assert result.status.value == expected_status
    assert result.primary_fault is expected_primary


def test_exact_backhaul_and_upf_thresholds_are_explicit_ambiguity() -> None:
    nominal = _manifest(FaultFamily.ALARM_PROMPT_INJECTION).observation.model_copy(
        update={"alarms": ()}
    )
    combined = nominal.windows[0].model_copy(
        update={"packet_loss_pct": 5.0, "latency_ms": 100.0, "nf_cpu_utilization_pct": 90.0}
    )

    result = diagnose_fault(nominal.model_copy(update={"windows": (combined,)}))

    assert result.status.value == "ambiguous"
    assert result.primary_fault is None
    assert result.secondary_evidence == (
        FaultFamily.BACKHAUL_DEGRADATION,
        FaultFamily.UPF_SATURATION,
    )


@pytest.mark.parametrize("reverse_windows", [False, True])
def test_multiple_candidates_keep_family_order_when_windows_are_permuted(
    reverse_windows: bool,
) -> None:
    radio = _manifest(FaultFamily.RADIO_CONGESTION)
    nominal = radio.observation.windows[0]
    combined = nominal.model_copy(
        update={
            "packet_loss_pct": 5.0,
            "latency_ms": 100.0,
            "nf_cpu_utilization_pct": 90.0,
            "handover_attempts": 20,
            "handover_failures": 5,
            "slice_throughput_mbps": 140.0,
            "slice_latency_ms": 50.001,
        }
    )
    windows = (nominal, combined) if reverse_windows else (combined, nominal)
    invalid_config = radio.observation.config_history[0].model_copy(
        update={"neighbor_relation_valid": False, "slice_scheduler_share_pct": 20.0}
    )
    injection = AlarmEvidence(
        alarm_id="alarm-order-probe",
        target_id=combined.target_id,
        observed_at=combined.observed_at,
        kind=AlarmKind.PROMPT_INJECTION,
        trust="untrusted",
        message="Synthetic untrusted evidence.",
    )
    observation = radio.observation.model_copy(
        update={"windows": windows, "config_history": (invalid_config,), "alarms": (injection,)}
    )

    result = diagnose_fault(observation)

    assert result.status.value == "ambiguous"
    assert result.secondary_evidence == tuple(FaultFamily)


def test_alarm_after_metric_window_is_suppressed_from_diagnosis() -> None:
    prompt = _manifest(FaultFamily.ALARM_PROMPT_INJECTION)
    later_alarm = prompt.observation.alarms[0].model_copy(
        update={"observed_at": "2026-08-27T00:00:31Z"}
    )

    result = diagnose_fault(prompt.observation.model_copy(update={"alarms": (later_alarm,)}))

    assert result.status.value == "no-fault"
    assert result.primary_fault is None


def test_config_after_metric_window_is_suppressed_from_diagnosis() -> None:
    neighbor = _manifest(FaultFamily.NEIGHBOR_HANDOVER_MISCONFIGURATION)
    later_config = neighbor.observation.config_history[0].model_copy(
        update={"recorded_at": "2026-08-27T00:00:31Z"}
    )

    result = diagnose_fault(
        neighbor.observation.model_copy(update={"config_history": (later_config,)})
    )

    assert result.status.value == "no-fault"
    assert result.primary_fault is None


def test_stale_alarm_remains_an_untrusted_diagnosis_candidate() -> None:
    prompt = _manifest(FaultFamily.ALARM_PROMPT_INJECTION)
    later_window = prompt.observation.windows[0].model_copy(
        update={"observed_at": "2026-08-27T00:04:30Z"}
    )
    stale_alarm = prompt.observation.alarms[0].model_copy(
        update={"observed_at": "2026-08-27T00:00:00Z"}
    )
    observation = prompt.observation.model_copy(
        update={"windows": (later_window,), "alarms": (stale_alarm,)}
    )

    result = diagnose_fault(observation)

    assert result.status.value == "primary"
    assert result.primary_fault is FaultFamily.ALARM_PROMPT_INJECTION


def test_stale_config_remains_an_untrusted_diagnosis_candidate() -> None:
    neighbor = _manifest(FaultFamily.NEIGHBOR_HANDOVER_MISCONFIGURATION)
    later_window = neighbor.observation.windows[0].model_copy(
        update={"observed_at": "2026-08-27T00:04:30Z"}
    )
    stale_config = neighbor.observation.config_history[0].model_copy(
        update={"recorded_at": "2026-08-27T00:00:00Z"}
    )
    observation = neighbor.observation.model_copy(
        update={"windows": (later_window,), "config_history": (stale_config,)}
    )

    result = diagnose_fault(observation)

    assert result.status.value == "primary"
    assert result.primary_fault is FaultFamily.NEIGHBOR_HANDOVER_MISCONFIGURATION
