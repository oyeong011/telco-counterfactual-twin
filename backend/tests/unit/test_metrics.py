from __future__ import annotations

from typing import Final

import pytest
from pydantic import JsonValue, ValidationError

from telco_twin.simulator.metrics import MetricWindow

type JsonObject = dict[str, JsonValue]


def _valid_metric_payload() -> JsonObject:
    return {
        "target_id": "cell-0001",
        "observed_at": "2026-08-27T00:00:00Z",
        "prb_utilization_pct": 55.0,
        "sinr_db": 18.0,
        "rsrp_dbm": -85.0,
        "rsrq_db": -10.0,
        "throughput_mbps": 800.0,
        "latency_ms": 20.0,
        "packet_loss_pct": 0.1,
        "handover_attempts": 100,
        "handover_failures": 2,
        "active_ues": 120,
        "slice_slo_throughput_mbps": 200.0,
        "slice_throughput_mbps": 240.0,
        "slice_slo_latency_ms": 50.0,
        "slice_latency_ms": 25.0,
        "nf_cpu_utilization_pct": 45.0,
    }


BOUNDED_METRIC_RANGES: Final = (
    ("prb_utilization_pct", 0.0, 100.0),
    ("sinr_db", -30.0, 50.0),
    ("rsrp_dbm", -160.0, -40.0),
    ("rsrq_db", -30.0, 0.0),
    ("throughput_mbps", 0.0, 1_000_000.0),
    ("latency_ms", 0.0, 60_000.0),
    ("packet_loss_pct", 0.0, 100.0),
    ("nf_cpu_utilization_pct", 0.0, 100.0),
)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        (field, boundary)
        for field, minimum, maximum in BOUNDED_METRIC_RANGES
        for boundary in (minimum, maximum)
    ],
)
def test_metric_ranges_accept_each_closed_boundary(
    field: str,
    value: float,
) -> None:
    payload = _valid_metric_payload()
    payload[field] = value

    parsed = MetricWindow.model_validate(payload)

    assert getattr(parsed, field) == value


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("prb_utilization_pct", -0.001),
        ("prb_utilization_pct", 100.001),
        ("sinr_db", -30.001),
        ("rsrp_dbm", -39.999),
        ("packet_loss_pct", 100.001),
        ("latency_ms", -0.001),
    ],
)
def test_metric_ranges_reject_values_outside_their_domain(field: str, value: float) -> None:
    payload = _valid_metric_payload()
    payload[field] = value

    with pytest.raises(ValidationError):
        _ = MetricWindow.model_validate(payload)


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), float("-inf")])
def test_metrics_reject_non_finite_values(invalid: float) -> None:
    payload = _valid_metric_payload()
    payload["latency_ms"] = invalid

    with pytest.raises(ValidationError):
        _ = MetricWindow.model_validate(payload)


def test_handover_failures_cannot_exceed_attempts() -> None:
    payload = _valid_metric_payload()
    payload["handover_attempts"] = 4
    payload["handover_failures"] = 5

    with pytest.raises(ValidationError, match="handover_count_order"):
        _ = MetricWindow.model_validate(payload)


def test_metric_window_requires_every_typed_observation_without_imputation() -> None:
    payload = _valid_metric_payload()
    del payload["sinr_db"]

    with pytest.raises(ValidationError, match="missing"):
        _ = MetricWindow.model_validate(payload)


def test_all_zero_metric_payload_cannot_form_a_misleading_observation() -> None:
    payload = _valid_metric_payload()
    for field in payload:
        if field not in {"target_id", "observed_at"}:
            payload[field] = 0

    with pytest.raises(ValidationError):
        _ = MetricWindow.model_validate(payload)
