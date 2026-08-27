"""Versioned synthetic network-observation manifests."""

from __future__ import annotations

from enum import StrEnum, unique
from typing import TYPE_CHECKING, Annotated, Literal, Self

from pydantic import Field, model_validator

from telco_twin.domain._contract import ContractId, RootContract, StrictContract, UtcTimestamp
from telco_twin.domain._validation import fail_validation
from telco_twin.domain.scenario import Scenario
from telco_twin.simulator.metrics import MetricWindow

if TYPE_CHECKING:
    from pathlib import Path


@unique
class AlarmKind(StrEnum):
    """Typed alarm classification kept separate from untrusted prose."""

    NETWORK_EVENT = "network-event"
    PROMPT_INJECTION = "prompt-injection"


class AlarmEvidence(StrictContract):
    """Untrusted alarm evidence whose message is never a decision input."""

    alarm_id: ContractId
    target_id: ContractId
    observed_at: UtcTimestamp
    kind: AlarmKind
    trust: Literal["untrusted"]
    message: Annotated[str, Field(min_length=1, max_length=1024)]


class ConfigSnapshot(StrictContract):
    """Typed synthetic configuration-history entry used as causal evidence."""

    config_version: ContractId
    target_id: ContractId
    recorded_at: UtcTimestamp
    neighbor_relation_valid: bool
    slice_scheduler_share_pct: Annotated[float, Field(strict=True, ge=0, le=100)]
    expected_slice_share_pct: Annotated[float, Field(strict=True, gt=0, le=100)]


class NetworkObservation(StrictContract):
    """Bounded typed telemetry, alarms, and config history for one scenario."""

    scenario_id: ContractId
    topology_id: ContractId
    windows: Annotated[tuple[MetricWindow, ...], Field(min_length=1, max_length=128)]
    alarms: Annotated[tuple[AlarmEvidence, ...], Field(max_length=64)]
    config_history: Annotated[tuple[ConfigSnapshot, ...], Field(min_length=1, max_length=128)]


class ScenarioManifest(RootContract):
    """Task-2-compatible scenario plus its bounded synthetic observation."""

    scenario: Scenario
    observation: NetworkObservation

    @model_validator(mode="after")
    def scenario_and_observation_are_bound(self) -> Self:
        """Require ID equality and a duplicate-free declared-target superset."""
        if (
            self.scenario.scenario_id != self.observation.scenario_id
            or self.scenario.topology_id != self.observation.topology_id
        ):
            fail_validation(
                "scenario_observation_binding",
                "scenario and observation identifiers do not match",
            )
        declared_targets = self.scenario.target_ids
        if len(set(declared_targets)) != len(declared_targets):
            fail_validation(
                "duplicate_scenario_target",
                "scenario target identifiers must be unique",
            )
        evidence_targets = (
            *(window.target_id for window in self.observation.windows),
            *(alarm.target_id for alarm in self.observation.alarms),
            *(config.target_id for config in self.observation.config_history),
        )
        if any(target not in declared_targets for target in evidence_targets):
            fail_validation(
                "scenario_evidence_target",
                "observation evidence target is not declared by the scenario",
            )
        return self


_ = ScenarioManifest.model_rebuild(
    _types_namespace={"Scenario": Scenario, "MetricWindow": MetricWindow}
)


def load_scenario_manifests(directory: Path) -> tuple[ScenarioManifest, ...]:
    """Parse committed manifests in stable byte-name order."""
    return tuple(
        ScenarioManifest.model_validate_json(path.read_text(encoding="utf-8"))
        for path in sorted(directory.glob("*.json"))
    )
