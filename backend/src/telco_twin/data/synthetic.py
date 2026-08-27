"""Seeded synthetic telecom input generation."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Final, Self, final

from pydantic import model_validator

from telco_twin.domain._contract import (
    ContractId,
    RootContract,
    SchemaVersion,
    Seed,
    SemanticVersion,
    Sha256Hex,
)
from telco_twin.domain._validation import fail_validation
from telco_twin.domain.scenario import FaultFamily, Scenario
from telco_twin.domain.topology import (
    ConfigRecord,
    NodeKind,
    Topology,
    TopologyLink,
    TopologyNode,
)
from telco_twin.simulator.hashing import HashContext, hash_contract

GENERATOR_VERSION: Final[SemanticVersion] = "1.0.0"
HASH_SCHEMA_VERSION: Final[SchemaVersion] = "1.0"
STARTED_AT: Final = "2026-08-27T00:00:00Z"
EMPTY_HASH: Final[Sha256Hex] = "0" * 64
MANIFEST_HASH_EXCLUDE: Final = frozenset({"manifest_hash"})


@final
class _DeterministicRng:
    """Mutable counter-based RNG isolated to one explicit simulator seed."""

    def __init__(self, seed: Seed) -> None:
        """Bind one seed with no process-global random state."""
        self._seed: bytes = seed.to_bytes(8, "big")
        self._counter: int = 0

    def integer(self, minimum: int, maximum: int) -> int:
        """Return one deterministic integer in the inclusive bounded range."""
        counter = self._counter.to_bytes(8, "big")
        self._counter += 1
        value = int.from_bytes(hashlib.sha256(self._seed + counter).digest()[:8], "big")
        return minimum + (value % ((maximum - minimum) + 1))

    def choice(self, values: tuple[int, ...]) -> int:
        """Choose one deterministic value from a fixed-order nonempty tuple."""
        return values[self.integer(0, len(values) - 1)]


@dataclass(frozen=True, slots=True)
class _LinkSpec:
    source_id: ContractId
    target_id: ContractId
    capacity_mbps: float
    latency_ms: float


class SimulationManifest(RootContract):
    """Versioned, content-hashed input for one deterministic simulator run."""

    manifest_id: ContractId
    input_version: SemanticVersion
    seed: Seed
    topology: Topology
    topology_hash: Sha256Hex
    scenario: Scenario
    scenario_hash: Sha256Hex
    manifest_hash: Sha256Hex

    @model_validator(mode="after")
    def manifest_references_are_consistent(self) -> Self:
        """Require one supported version, seed, and topology identity."""
        if self.input_version != GENERATOR_VERSION:
            fail_validation("unsupported_input_version", "manifest input version is unsupported")
        if self.seed != self.topology.seed or self.seed != self.scenario.seed:
            fail_validation("manifest_seed_mismatch", "manifest seeds must match")
        if self.scenario.topology_id != self.topology.topology_id:
            fail_validation("manifest_topology_mismatch", "scenario topology does not match")
        return self


def _hash_context(input_name: str, seed: Seed) -> HashContext:
    return HashContext(
        schema_version=HASH_SCHEMA_VERSION,
        input_name=input_name,
        input_version=GENERATOR_VERSION,
        seed=seed,
    )


def _generate_topology(seed: Seed, rng: _DeterministicRng) -> Topology:
    cell_count = rng.integer(2, 4)
    nodes: list[TopologyNode] = []
    link_specs: list[_LinkSpec] = []
    for index in range(1, cell_count + 1):
        cell_id = f"cell-{index:04d}"
        gnb_id = f"gnb-{index:04d}"
        cohort_id = f"ue-cohort-{index:04d}"
        nodes.extend(
            (
                TopologyNode(
                    node_id=cell_id,
                    kind=NodeKind.CELL,
                    attributes={
                        "band_mhz": rng.choice((700, 1800, 3500)),
                        "capacity_ues": rng.integer(60, 160),
                    },
                ),
                TopologyNode(
                    node_id=gnb_id,
                    kind=NodeKind.GNB,
                    attributes={"tx_power_dbm": rng.integer(30, 46)},
                ),
                TopologyNode(
                    node_id=cohort_id,
                    kind=NodeKind.UE_COHORT,
                    attributes={"active_ues": rng.integer(10, 55)},
                ),
            )
        )
        link_specs.extend(
            (
                _LinkSpec(cohort_id, cell_id, 500.0, 1.0),
                _LinkSpec(cell_id, gnb_id, 2_000.0, 0.5),
                _LinkSpec(gnb_id, "backhaul-0001", float(rng.integer(800, 1600)), 2.0),
            )
        )
    nodes.extend(
        (
            TopologyNode(
                node_id="backhaul-0001",
                kind=NodeKind.BACKHAUL,
                attributes={"capacity_mbps": rng.integer(5_000, 10_000)},
            ),
            TopologyNode(
                node_id="amf-0001",
                kind=NodeKind.AMF,
                attributes={"capacity_units": rng.integer(80, 120)},
            ),
            TopologyNode(
                node_id="smf-0001",
                kind=NodeKind.SMF,
                attributes={"capacity_units": rng.integer(80, 120)},
            ),
            TopologyNode(
                node_id="upf-0001",
                kind=NodeKind.UPF,
                attributes={"capacity_units": rng.integer(80, 120)},
            ),
            TopologyNode(
                node_id="slice-embb",
                kind=NodeKind.SLICE,
                attributes={"scheduler_weight": rng.integer(50, 80)},
            ),
            TopologyNode(
                node_id="slice-urllc",
                kind=NodeKind.SLICE,
                attributes={"scheduler_weight": rng.integer(20, 50)},
            ),
        )
    )
    link_specs.extend(
        (
            _LinkSpec("backhaul-0001", "upf-0001", 10_000.0, 4.0),
            _LinkSpec("amf-0001", "smf-0001", 5_000.0, 1.0),
            _LinkSpec("smf-0001", "upf-0001", 5_000.0, 1.0),
            _LinkSpec("slice-embb", "upf-0001", 5_000.0, 0.0),
            _LinkSpec("slice-urllc", "upf-0001", 5_000.0, 0.0),
        )
    )
    links = tuple(
        TopologyLink(
            link_id=f"link-{index:04d}",
            source_id=spec.source_id,
            target_id=spec.target_id,
            capacity_mbps=spec.capacity_mbps,
            latency_ms=spec.latency_ms,
        )
        for index, spec in enumerate(link_specs, start=1)
    )
    return Topology(
        topology_id=f"topology-{seed:013x}",
        seed=seed,
        nodes=tuple(nodes),
        links=links,
        config_history=(
            ConfigRecord(
                config_version="config-0001",
                recorded_at=STARTED_AT,
                changes={"handover_margin_db": rng.integer(2, 6)},
            ),
            ConfigRecord(
                config_version="config-0002",
                recorded_at="2026-08-27T00:01:00Z",
                changes={"scheduler_weight": rng.integer(10, 30)},
            ),
        ),
        schema_version="1.0",
    )


def _generate_scenario(topology: Topology, seed: Seed) -> Scenario:
    return Scenario(
        scenario_id=f"scenario-{seed:013x}",
        topology_id=topology.topology_id,
        seed=seed,
        fault_family=FaultFamily.RADIO_CONGESTION,
        starts_at=STARTED_AT,
        duration_seconds=60,
        target_ids=("cell-0001",),
        parameters={"load_percent": 90 + (seed % 10)},
        schema_version="1.0",
    )


def generate_manifest(seed: Seed) -> SimulationManifest:
    """Generate one versioned manifest using only an isolated seeded RNG."""
    rng = _DeterministicRng(seed)
    topology = _generate_topology(seed, rng)
    scenario = _generate_scenario(topology, seed)
    draft = SimulationManifest(
        manifest_id=f"manifest-{seed:013x}",
        input_version=GENERATOR_VERSION,
        seed=seed,
        topology=topology,
        topology_hash=hash_contract(topology, _hash_context("topology", seed)),
        scenario=scenario,
        scenario_hash=hash_contract(scenario, _hash_context("scenario", seed)),
        manifest_hash=EMPTY_HASH,
        schema_version="1.0",
    )
    return draft.model_copy(
        update={
            "manifest_hash": hash_contract(
                draft,
                _hash_context("simulation-manifest", seed),
                exclude=MANIFEST_HASH_EXCLUDE,
            )
        }
    )
