"""Deterministic simulator execution engine."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Final, override

from telco_twin.data.synthetic import (
    GENERATOR_VERSION,
    HASH_SCHEMA_VERSION,
    MANIFEST_HASH_EXCLUDE,
    SimulationManifest,
)
from telco_twin.domain._contract import Seed, SemanticVersion, Sha256Hex, utc_datetime
from telco_twin.domain.event import Event
from telco_twin.simulator.hashing import (
    HashContext,
    TraceHashInput,
    hash_contract,
    hash_trace,
)
from telco_twin.simulator.scheduler import DeterministicScheduler

if TYPE_CHECKING:
    from telco_twin.simulator.frozen_event import FrozenEvent

SIMULATOR_VERSION: Final[SemanticVersion] = "1.0.0"


@dataclass(frozen=True, slots=True)
class ManifestIntegrityError(Exception):
    """A manifest or one of its bound inputs no longer matches its digest."""

    component: str
    expected_hash: Sha256Hex
    actual_hash: Sha256Hex

    @override
    def __str__(self) -> str:
        """Return a stable component-level integrity diagnostic."""
        return (
            f"{self.component} hash mismatch: expected {self.expected_hash}, "
            f"computed {self.actual_hash}"
        )


@dataclass(frozen=True, slots=True)
class SimulationTrace:
    """Immutable nonempty output of one verified deterministic run."""

    manifest_hash: Sha256Hex
    topology_hash: Sha256Hex
    events: tuple[FrozenEvent, ...]
    trace_hash: Sha256Hex


def _hash_context(input_name: str, seed: Seed) -> HashContext:
    return HashContext(
        schema_version=HASH_SCHEMA_VERSION,
        input_name=input_name,
        input_version=GENERATOR_VERSION,
        seed=seed,
    )


def _require_hash(
    component: str,
    expected_hash: Sha256Hex,
    actual_hash: Sha256Hex,
) -> None:
    if actual_hash != expected_hash:
        raise ManifestIntegrityError(
            component=component,
            expected_hash=expected_hash,
            actual_hash=actual_hash,
        )


def _verify_manifest(manifest: SimulationManifest) -> None:
    _require_hash(
        "simulation-manifest",
        manifest.manifest_hash,
        hash_contract(
            manifest,
            _hash_context("simulation-manifest", manifest.seed),
            exclude=MANIFEST_HASH_EXCLUDE,
        ),
    )
    _require_hash(
        "topology",
        manifest.topology_hash,
        hash_contract(manifest.topology, _hash_context("topology", manifest.seed)),
    )
    _require_hash(
        "scenario",
        manifest.scenario_hash,
        hash_contract(manifest.scenario, _hash_context("scenario", manifest.seed)),
    )


def _events_for(manifest: SimulationManifest) -> tuple[Event, ...]:
    events: list[Event] = [
        Event(
            event_id="event-0000",
            scenario_id=manifest.scenario.scenario_id,
            timestamp=manifest.scenario.starts_at,
            priority=-100,
            sequence_id=0,
            event_type="simulation-started",
            payload={"manifest_hash": manifest.manifest_hash},
            schema_version="1.0",
        )
    ]
    for sequence_id, node in enumerate(
        sorted(manifest.topology.nodes, key=lambda item: item.node_id),
        start=1,
    ):
        events.append(
            Event(
                event_id=f"event-{sequence_id:04d}",
                scenario_id=manifest.scenario.scenario_id,
                timestamp=manifest.scenario.starts_at,
                priority=0,
                sequence_id=sequence_id,
                event_type="topology-node-ready",
                payload={"node_id": node.node_id, "node_kind": node.kind.value},
                schema_version="1.0",
            )
        )
    completed_sequence = len(events)
    completed_at = (
        utc_datetime(manifest.scenario.starts_at)
        + timedelta(seconds=manifest.scenario.duration_seconds)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    events.append(
        Event(
            event_id=f"event-{completed_sequence:04d}",
            scenario_id=manifest.scenario.scenario_id,
            timestamp=completed_at,
            priority=100,
            sequence_id=completed_sequence,
            event_type="simulation-completed",
            payload={"event_count": completed_sequence + 1},
            schema_version="1.0",
        )
    )
    return tuple(events)


def run_simulation(manifest: SimulationManifest) -> SimulationTrace:
    """Verify a manifest, schedule its events, and return a canonical trace."""
    _verify_manifest(manifest)
    scheduler = DeterministicScheduler()
    for event in _events_for(manifest):
        scheduler.schedule(event)
    events = scheduler.drain().events
    trace_input = TraceHashInput(
        manifest_hash=manifest.manifest_hash,
        events=events,
    )
    return SimulationTrace(
        manifest_hash=manifest.manifest_hash,
        topology_hash=manifest.topology_hash,
        events=events,
        trace_hash=hash_trace(
            trace_input,
            HashContext(
                schema_version=HASH_SCHEMA_VERSION,
                input_name="simulation-trace",
                input_version=SIMULATOR_VERSION,
                seed=manifest.seed,
            ),
        ),
    )
