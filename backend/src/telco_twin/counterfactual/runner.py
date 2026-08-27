"""Immutable deterministic baseline and candidate simulation forks."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, assert_never

from telco_twin.counterfactual.patches import (
    PatchAccepted,
    PatchRejected,
    assess_patch,
)
from telco_twin.data.synthetic import (
    GENERATOR_VERSION,
    HASH_SCHEMA_VERSION,
    MANIFEST_HASH_EXCLUDE,
    SimulationManifest,
)
from telco_twin.domain.canonical import canonical_model_bytes
from telco_twin.domain.intervention import PatchOperation, TypedPatch
from telco_twin.domain.topology import ConfigRecord, Topology, TopologyNode
from telco_twin.simulator.engine import SimulationTrace, run_simulation
from telco_twin.simulator.hashing import HashContext, hash_contract

if TYPE_CHECKING:
    from telco_twin.domain._contract import Sha256Hex
    from telco_twin.domain.scenario import Scenario

CANDIDATE_SUFFIX: Final = "candidate"


@dataclass(frozen=True, slots=True)
class CounterfactualRejected:
    """Patch rejection returned before either simulation is exposed."""

    assessment: PatchRejected


@dataclass(frozen=True, slots=True)
class CounterfactualRun:
    """Complete immutable baseline/candidate evidence for one typed patch."""

    patch: TypedPatch
    patch_hash: Sha256Hex
    baseline_manifest: SimulationManifest
    candidate_manifest: SimulationManifest
    baseline_trace: SimulationTrace
    candidate_trace: SimulationTrace
    replay_trace: SimulationTrace
    baseline_state_hash_before: Sha256Hex
    baseline_state_hash_after: Sha256Hex


type CounterfactualOutcome = CounterfactualRun | CounterfactualRejected


def _context(input_name: str, manifest: SimulationManifest) -> HashContext:
    return HashContext(
        schema_version=HASH_SCHEMA_VERSION,
        input_name=input_name,
        input_version=GENERATOR_VERSION,
        seed=manifest.seed,
    )


def _node_with_change(node: TopologyNode, patch: TypedPatch) -> TopologyNode:
    attributes = dict(node.attributes)
    for change in patch.changes:
        if change.target_id != node.node_id:
            continue
        match change.operation:
            case PatchOperation.ADJUST_RADIO_CAPACITY:
                attributes["capacity_ues"] = change.parameters["capacity_ues"]
            case PatchOperation.RESTORE_BACKHAUL_CAPACITY:
                attributes["capacity_mbps"] = change.parameters["capacity_mbps"]
            case PatchOperation.SCALE_UPF_CAPACITY:
                attributes["capacity_units"] = change.parameters["capacity_units"]
            case PatchOperation.REBALANCE_SLICE_WEIGHT:
                attributes["scheduler_weight"] = change.parameters["scheduler_weight"]
            case PatchOperation.CORRECT_NEIGHBOR_RELATION | PatchOperation.IGNORE_UNTRUSTED_ALARM:
                pass
            case _:  # pragma: no cover - exhaustive enum
                assert_never(change.operation)
    return node.model_copy(update={"attributes": attributes})


def _candidate_topology(manifest: SimulationManifest, patch: TypedPatch) -> Topology:
    records = list(manifest.topology.config_history)
    for index, change in enumerate(patch.changes, start=1):
        match change.operation:
            case PatchOperation.CORRECT_NEIGHBOR_RELATION:
                records.append(
                    ConfigRecord(
                        config_version=f"{patch.patch_id}-{CANDIDATE_SUFFIX}-{index}",
                        recorded_at=patch.proposed_at,
                        changes={
                            "relation_valid": change.parameters["relation_valid"],
                            "target_ref": change.target_id,
                        },
                    )
                )
            case (
                PatchOperation.ADJUST_RADIO_CAPACITY
                | PatchOperation.RESTORE_BACKHAUL_CAPACITY
                | PatchOperation.SCALE_UPF_CAPACITY
                | PatchOperation.REBALANCE_SLICE_WEIGHT
                | PatchOperation.IGNORE_UNTRUSTED_ALARM
            ):
                pass
            case _:  # pragma: no cover - exhaustive enum
                assert_never(change.operation)
    return manifest.topology.model_copy(
        update={
            "nodes": tuple(_node_with_change(node, patch) for node in manifest.topology.nodes),
            "config_history": tuple(records),
        }
    )


def _candidate_scenario(manifest: SimulationManifest, patch: TypedPatch) -> Scenario:
    parameters = dict(manifest.scenario.parameters)
    for change in patch.changes:
        match change.operation:
            case PatchOperation.IGNORE_UNTRUSTED_ALARM:
                parameters["alarm_ignored"] = change.parameters["alarm_ignored"]
            case (
                PatchOperation.ADJUST_RADIO_CAPACITY
                | PatchOperation.RESTORE_BACKHAUL_CAPACITY
                | PatchOperation.SCALE_UPF_CAPACITY
                | PatchOperation.CORRECT_NEIGHBOR_RELATION
                | PatchOperation.REBALANCE_SLICE_WEIGHT
            ):
                pass
            case _:  # pragma: no cover - exhaustive enum
                assert_never(change.operation)
    return manifest.scenario.model_copy(update={"parameters": parameters})


def _fork_manifest(manifest: SimulationManifest, patch: TypedPatch) -> SimulationManifest:
    topology = _candidate_topology(manifest, patch)
    scenario = _candidate_scenario(manifest, patch)
    draft = manifest.model_copy(
        update={
            "manifest_id": f"{manifest.manifest_id}-{CANDIDATE_SUFFIX}",
            "topology": topology,
            "topology_hash": hash_contract(topology, _context("topology", manifest)),
            "scenario": scenario,
            "scenario_hash": hash_contract(scenario, _context("scenario", manifest)),
            "manifest_hash": "0" * 64,
        }
    )
    return draft.model_copy(
        update={
            "manifest_hash": hash_contract(
                draft,
                _context("simulation-manifest", manifest),
                exclude=MANIFEST_HASH_EXCLUDE,
            )
        }
    )


def _state_hash(manifest: SimulationManifest) -> Sha256Hex:
    return hashlib.sha256(canonical_model_bytes(manifest)).hexdigest()


def run_counterfactual(
    manifest: SimulationManifest,
    patch: TypedPatch,
) -> CounterfactualOutcome:
    """Run baseline and patched forks without mutating caller-owned state."""
    assessment = assess_patch(patch, manifest)
    match assessment:
        case PatchRejected():
            return CounterfactualRejected(assessment)
        case PatchAccepted(patch_hash=patch_hash):
            baseline_before = _state_hash(manifest)
            baseline = SimulationManifest.model_validate_json(manifest.model_dump_json())
            baseline_trace = run_simulation(baseline)
            candidate = _fork_manifest(baseline, patch)
            candidate_trace = run_simulation(candidate)
            replay_trace = run_simulation(candidate)
            return CounterfactualRun(
                patch=TypedPatch.model_validate_json(patch.model_dump_json()),
                patch_hash=patch_hash,
                baseline_manifest=baseline,
                candidate_manifest=candidate,
                baseline_trace=baseline_trace,
                candidate_trace=candidate_trace,
                replay_trace=replay_trace,
                baseline_state_hash_before=baseline_before,
                baseline_state_hash_after=_state_hash(manifest),
            )
        case _:  # pragma: no cover - exhaustive typed union
            assert_never(assessment)
