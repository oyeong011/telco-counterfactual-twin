from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Final, TypedDict

import pytest
from pydantic import TypeAdapter, ValidationError

from telco_twin.domain.scenario import Scenario
from telco_twin.simulator.network_model import (
    AlarmEvidence,
    AlarmKind,
    ConfigSnapshot,
    NetworkObservation,
    ScenarioManifest,
    load_scenario_manifests,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

SCENARIO_FIXTURES: Final = Path(__file__).parents[2] / "fixtures/scenarios"


class _BooleanSchema(TypedDict):
    type: str


class _ConfigProperties(TypedDict):
    neighbor_relation_valid: _BooleanSchema


class _ConfigSchema(TypedDict):
    properties: _ConfigProperties


CONFIG_SCHEMA_ADAPTER: Final[TypeAdapter[_ConfigSchema]] = TypeAdapter(_ConfigSchema)


def _radio_manifest() -> ScenarioManifest:
    return load_scenario_manifests(SCENARIO_FIXTURES)[0]


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


def test_scenario_manifest_rejects_empty_declared_targets() -> None:
    manifest = _radio_manifest()

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


@pytest.mark.parametrize("json_value", ['"false"', '"true"', "0", "1", '"yes"', "null", "[]", "{}"])
def test_manifest_loader_rejects_coercive_config_boolean(
    tmp_path: Path,
    json_value: str,
) -> None:
    source = (SCENARIO_FIXTURES / "04-neighbor-handover-misconfiguration-v1.json").read_text(
        encoding="utf-8"
    )
    malformed = source.replace(
        '"neighbor_relation_valid": false', f'"neighbor_relation_valid": {json_value}'
    )
    _ = (tmp_path / "scenario.json").write_text(malformed, encoding="utf-8")

    with pytest.raises(ValidationError) as caught:
        _ = load_scenario_manifests(tmp_path)

    assert "bool_type" in {item["type"] for item in caught.value.errors()}


@pytest.mark.parametrize(("json_value", "expected"), [("false", False), ("true", True)])
def test_manifest_loader_accepts_only_json_booleans(
    tmp_path: Path,
    json_value: str,
    expected: bool,
) -> None:
    source = (SCENARIO_FIXTURES / "04-neighbor-handover-misconfiguration-v1.json").read_text(
        encoding="utf-8"
    )
    valid = source.replace(
        '"neighbor_relation_valid": false', f'"neighbor_relation_valid": {json_value}'
    )
    _ = (tmp_path / "scenario.json").write_text(valid, encoding="utf-8")

    loaded = load_scenario_manifests(tmp_path)

    assert loaded[0].observation.config_history[0].neighbor_relation_valid is expected


def test_config_schema_declares_neighbor_relation_as_boolean() -> None:
    schema = CONFIG_SCHEMA_ADAPTER.validate_python(ConfigSnapshot.model_json_schema())

    assert schema["properties"]["neighbor_relation_valid"]["type"] == "boolean"
