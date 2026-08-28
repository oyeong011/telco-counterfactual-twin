"""Synthetic scenario/observation assembly over committed typed fixtures."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, final

from telco_twin.data.synthetic import (
    GENERATOR_VERSION,
    HASH_SCHEMA_VERSION,
    MANIFEST_HASH_EXCLUDE,
    SimulationManifest,
    generate_manifest,
)
from telco_twin.domain.scenario import FaultFamily, Scenario
from telco_twin.simulator.hashing import HashContext, hash_contract
from telco_twin.simulator.network_model import NetworkObservation, ScenarioManifest

if TYPE_CHECKING:
    from pathlib import Path

    from telco_twin.domain._contract import ContractId, Seed, UtcTimestamp

TARGET_ALIASES: Final = {
    "slice-0001": "slice-embb",
}


def _context(name: str, seed: Seed) -> HashContext:
    return HashContext(
        schema_version=HASH_SCHEMA_VERSION,
        input_name=name,
        input_version=GENERATOR_VERSION,
        seed=seed,
    )


def _target(value: str) -> str:
    return TARGET_ALIASES.get(value, value)


def _observation(
    source: NetworkObservation,
    scenario: Scenario,
    observed_at: UtcTimestamp,
) -> NetworkObservation:
    return source.model_copy(
        update={
            "scenario_id": scenario.scenario_id,
            "topology_id": scenario.topology_id,
            "windows": tuple(
                window.model_copy(
                    update={"target_id": _target(window.target_id), "observed_at": observed_at}
                )
                for window in source.windows
            ),
            "alarms": tuple(
                alarm.model_copy(
                    update={"target_id": _target(alarm.target_id), "observed_at": observed_at}
                )
                for alarm in source.alarms
            ),
            "config_history": tuple(
                config.model_copy(
                    update={"target_id": _target(config.target_id), "recorded_at": observed_at}
                )
                for config in source.config_history
            ),
        }
    )


@final
class ScenarioFactory:
    """Build simulation manifests from the six committed fault fixtures."""

    def __init__(self, fixture_directory: Path) -> None:
        """Load the exact six committed fixture families."""
        fixtures = tuple(
            ScenarioManifest.model_validate_json(path.read_bytes())
            for path in sorted(fixture_directory.glob("*.json"))
        )
        self._fixtures = {item.scenario.fault_family: item for item in fixtures}
        if frozenset(self._fixtures) != frozenset(FaultFamily):
            msg = "scenario fixture set is incomplete"
            raise RuntimeError(msg)

    def build(
        self,
        scenario_id: ContractId,
        seed: Seed,
        family: FaultFamily,
        starts_at: UtcTimestamp,
    ) -> tuple[SimulationManifest, NetworkObservation]:
        """Bind one selected fixture to a fresh deterministic topology and time."""
        base = generate_manifest(seed)
        fixture = self._fixtures[family]
        scenario = fixture.scenario.model_copy(
            update={
                "scenario_id": scenario_id,
                "topology_id": base.topology.topology_id,
                "seed": seed,
                "starts_at": starts_at,
                "target_ids": tuple(_target(value) for value in fixture.scenario.target_ids),
            }
        )
        draft = base.model_copy(
            update={
                "scenario": scenario,
                "scenario_hash": hash_contract(scenario, _context("scenario", seed)),
                "manifest_hash": "0" * 64,
            }
        )
        manifest = draft.model_copy(
            update={
                "manifest_hash": hash_contract(
                    draft,
                    _context("simulation-manifest", seed),
                    exclude=MANIFEST_HASH_EXCLUDE,
                )
            }
        )
        return manifest, _observation(fixture.observation, scenario, starts_at)
