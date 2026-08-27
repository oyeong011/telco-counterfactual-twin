from __future__ import annotations

import json
from pathlib import Path
from typing import ClassVar, Final

import pytest
from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError

from telco_twin.simulator.metrics import MetricWindow
from telco_twin.simulator.network_model import (
    AlarmEvidence,
    AlarmKind,
    NetworkObservation,
    ScenarioManifest,
    load_scenario_manifests,
)

type JsonObject = dict[str, JsonValue]
SCENARIO_FIXTURES: Final = Path(__file__).parents[2] / "fixtures/scenarios"

FLOAT_METRIC_FIELDS: Final = (
    "prb_utilization_pct",
    "sinr_db",
    "rsrp_dbm",
    "rsrq_db",
    "throughput_mbps",
    "latency_ms",
    "packet_loss_pct",
    "slice_slo_throughput_mbps",
    "slice_throughput_mbps",
    "slice_slo_latency_ms",
    "slice_latency_ms",
    "nf_cpu_utilization_pct",
)
INTEGER_METRIC_FIELDS: Final = ("handover_attempts", "handover_failures", "active_ues")


class _SchemaProperty(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    type: str | None = None
    ref: str | None = Field(default=None, alias="$ref")


class _MetricSchema(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    definitions: dict[str, _SchemaProperty] = Field(alias="$defs")
    properties: dict[str, _SchemaProperty]


def _radio_manifest() -> ScenarioManifest:
    return load_scenario_manifests(SCENARIO_FIXTURES)[0]


def _schema_type(schema: _MetricSchema, field: str) -> str:
    property_schema = schema.properties[field]
    if property_schema.type is not None:
        return property_schema.type
    assert property_schema.ref is not None
    definition = property_schema.ref.rsplit("/", maxsplit=1)[-1]
    resolved = schema.definitions[definition].type
    assert resolved is not None
    return resolved


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

    with pytest.raises(ValidationError) as caught:
        _ = MetricWindow.model_validate_json(json.dumps(payload))

    assert "finite_number" in {item["type"] for item in caught.value.errors()}


@pytest.mark.parametrize("field", FLOAT_METRIC_FIELDS)
@pytest.mark.parametrize("invalid", [True, False, "95.0"])
def test_json_float_metrics_reject_coercive_scalars(field: str, invalid: bool | str) -> None:
    payload = _valid_metric_payload()
    payload[field] = invalid

    with pytest.raises(ValidationError) as caught:
        _ = MetricWindow.model_validate_json(json.dumps(payload))

    assert "float_type" in {item["type"] for item in caught.value.errors()}


@pytest.mark.parametrize("field", INTEGER_METRIC_FIELDS)
@pytest.mark.parametrize("invalid", [True, False, "95.0"])
def test_json_integer_metrics_reject_coercive_scalars(field: str, invalid: bool | str) -> None:
    payload = _valid_metric_payload()
    payload[field] = invalid

    with pytest.raises(ValidationError) as caught:
        _ = MetricWindow.model_validate_json(json.dumps(payload))

    assert "int_type" in {item["type"] for item in caught.value.errors()}


def test_json_numbers_preserve_integer_fields_and_normalize_float_fields() -> None:
    payload = _valid_metric_payload()
    payload["prb_utilization_pct"] = 95
    payload["active_ues"] = 500

    parsed = MetricWindow.model_validate_json(json.dumps(payload))

    assert parsed.prb_utilization_pct == 95.0
    assert type(parsed.prb_utilization_pct) is float
    assert parsed.active_ues == 500
    assert type(parsed.active_ues) is int


def test_metric_json_schema_keeps_float_and_integer_domains_distinct() -> None:
    schema = _MetricSchema.model_validate(MetricWindow.model_json_schema())

    assert {_schema_type(schema, field) for field in FLOAT_METRIC_FIELDS} == {"number"}
    assert {_schema_type(schema, field) for field in INTEGER_METRIC_FIELDS} == {"integer"}


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


def test_scenario_manifest_rejects_stale_schema() -> None:
    manifest = _radio_manifest()
    payload = manifest.model_dump(mode="json")
    payload["schema_version"] = "0.9"

    with pytest.raises(ValidationError):
        _ = ScenarioManifest.model_validate(payload)


def test_scenario_manifest_rejects_mismatched_ids() -> None:
    manifest = _radio_manifest()
    mismatched = manifest.observation.model_copy(update={"scenario_id": "scenario-other"})

    with pytest.raises(ValidationError, match="scenario_observation_binding"):
        _ = ScenarioManifest(
            schema_version="1.0",
            scenario=manifest.scenario,
            observation=mismatched,
        )


def test_scenario_manifest_rejects_unrelated_metric_target() -> None:
    manifest = _radio_manifest()
    unrelated = manifest.observation.windows[0].model_copy(update={"target_id": "unrelated-0009"})

    with pytest.raises(ValidationError, match="scenario_evidence_target"):
        _ = ScenarioManifest(
            schema_version="1.0",
            scenario=manifest.scenario,
            observation=manifest.observation.model_copy(update={"windows": (unrelated,)}),
        )


def test_scenario_manifest_rejects_unrelated_alarm_target() -> None:
    manifest = _radio_manifest()
    unrelated = AlarmEvidence(
        alarm_id="alarm-binding-probe",
        target_id="unrelated-0009",
        observed_at="2026-08-27T00:00:30Z",
        kind=AlarmKind.NETWORK_EVENT,
        trust="untrusted",
        message="Synthetic evidence.",
    )

    with pytest.raises(ValidationError, match="scenario_evidence_target"):
        _ = ScenarioManifest(
            schema_version="1.0",
            scenario=manifest.scenario,
            observation=manifest.observation.model_copy(update={"alarms": (unrelated,)}),
        )


def test_scenario_manifest_rejects_unrelated_config_target() -> None:
    manifest = _radio_manifest()
    unrelated = manifest.observation.config_history[0].model_copy(
        update={"target_id": "unrelated-0009"}
    )

    with pytest.raises(ValidationError, match="scenario_evidence_target"):
        _ = ScenarioManifest(
            schema_version="1.0",
            scenario=manifest.scenario,
            observation=manifest.observation.model_copy(update={"config_history": (unrelated,)}),
        )


def test_scenario_manifest_rejects_duplicate_declared_targets() -> None:
    manifest = _radio_manifest()
    duplicated = manifest.scenario.model_copy(update={"target_ids": ("cell-0001", "cell-0001")})

    with pytest.raises(ValidationError, match="duplicate_scenario_target"):
        _ = ScenarioManifest(
            schema_version="1.0",
            scenario=duplicated,
            observation=manifest.observation,
        )


def test_network_observation_rejects_empty_metric_binding() -> None:
    manifest = _radio_manifest()

    with pytest.raises(ValidationError, match="too_short"):
        _ = NetworkObservation(
            scenario_id=manifest.observation.scenario_id,
            topology_id=manifest.observation.topology_id,
            windows=(),
            alarms=manifest.observation.alarms,
            config_history=manifest.observation.config_history,
        )


def test_network_observation_rejects_empty_config_binding() -> None:
    manifest = _radio_manifest()

    with pytest.raises(ValidationError, match="too_short"):
        _ = NetworkObservation(
            scenario_id=manifest.observation.scenario_id,
            topology_id=manifest.observation.topology_id,
            windows=manifest.observation.windows,
            alarms=manifest.observation.alarms,
            config_history=(),
        )
