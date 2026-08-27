"""Typed baseline/candidate metric and evidence comparison."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, assert_never, override

from telco_twin.counterfactual.constraints import build_constraint_results
from telco_twin.domain._contract import ContractId, Sha256Hex, StrictContract, utc_datetime
from telco_twin.domain.canonical import canonical_model_bytes
from telco_twin.domain.intervention import PatchOperation
from telco_twin.domain.simulation_result import MetricDelta, SimulationResult

if TYPE_CHECKING:
    from telco_twin.counterfactual.runner import CounterfactualRun


@dataclass(frozen=True, slots=True)
class CounterfactualMetricError(Exception):
    """A validated patch did not produce its promised numeric topology value."""

    parameter: str

    @override
    def __str__(self) -> str:
        return f"counterfactual metric is not numeric: {self.parameter}"


class _MetricCandidate(StrictContract):
    value: str | int | float | bool | None
    parameter: str


class ComparisonEvidenceHashes(StrictContract):
    """Independent content identities needed to audit one comparison."""

    patch_hash: Sha256Hex
    baseline_manifest_hash: Sha256Hex
    candidate_manifest_hash: Sha256Hex
    baseline_trace_hash: Sha256Hex
    candidate_trace_hash: Sha256Hex
    constraint_set_hash: Sha256Hex


class CounterfactualComparison(StrictContract):
    """Simulation result plus every directly supporting evidence hash."""

    result: SimulationResult
    evidence_hashes: ComparisonEvidenceHashes


def _numeric(candidate: _MetricCandidate) -> float:
    match candidate.value:
        case bool() | str() | None:
            raise CounterfactualMetricError(candidate.parameter)
        case int() | float() as number:
            return float(number)
        case _:  # pragma: no cover - exhaustive scalar union
            assert_never(candidate.value)


def _node_value(run: CounterfactualRun, target_id: str, parameter: str) -> tuple[float, float]:
    baseline = next(
        node for node in run.baseline_manifest.topology.nodes if node.node_id == target_id
    )
    candidate = next(
        node for node in run.candidate_manifest.topology.nodes if node.node_id == target_id
    )
    return (
        _numeric(_MetricCandidate(value=baseline.attributes[parameter], parameter=parameter)),
        _numeric(_MetricCandidate(value=candidate.attributes[parameter], parameter=parameter)),
    )


def _metric(run: CounterfactualRun, index: int) -> MetricDelta:
    change = run.patch.changes[index]
    match change.operation:
        case PatchOperation.ADJUST_RADIO_CAPACITY:
            name, unit = "capacity-ues", "count"
            baseline, candidate = _node_value(run, change.target_id, "capacity_ues")
        case PatchOperation.RESTORE_BACKHAUL_CAPACITY:
            name, unit = "capacity-mbps", "mbps"
            baseline, candidate = _node_value(run, change.target_id, "capacity_mbps")
        case PatchOperation.SCALE_UPF_CAPACITY:
            name, unit = "capacity-units", "count"
            baseline, candidate = _node_value(run, change.target_id, "capacity_units")
        case PatchOperation.CORRECT_NEIGHBOR_RELATION:
            name, unit = "relation-valid", "boolean"
            baseline, candidate = 0.0, 1.0
        case PatchOperation.REBALANCE_SLICE_WEIGHT:
            name, unit = "scheduler-weight", "count"
            baseline, candidate = _node_value(run, change.target_id, "scheduler_weight")
        case PatchOperation.IGNORE_UNTRUSTED_ALARM:
            name, unit = "alarm-ignored", "boolean"
            baseline, candidate = 0.0, 1.0
        case _:  # pragma: no cover - exhaustive enum
            assert_never(change.operation)
    return MetricDelta(metric_name=name, baseline=baseline, candidate=candidate, unit=unit)


def _completed_at(run: CounterfactualRun) -> str:
    completed = utc_datetime(run.baseline_manifest.scenario.starts_at) + timedelta(
        seconds=run.baseline_manifest.scenario.duration_seconds
    )
    return completed.strftime("%Y-%m-%dT%H:%M:%SZ")


def compare_counterfactual(
    run: CounterfactualRun,
    simulation_id: ContractId,
) -> CounterfactualComparison:
    """Compare a verified run without consulting wall clock or prose."""
    constraints = build_constraint_results(run)
    result = SimulationResult(
        simulation_id=simulation_id,
        scenario_id=run.baseline_manifest.scenario.scenario_id,
        patch_hash=run.patch_hash,
        baseline_hash=run.baseline_trace.trace_hash,
        candidate_hash=run.candidate_trace.trace_hash,
        trace_hash=run.candidate_trace.trace_hash,
        started_at=run.baseline_manifest.scenario.starts_at,
        completed_at=_completed_at(run),
        metric_deltas=tuple(_metric(run, index) for index in range(len(run.patch.changes))),
        constraints=constraints,
        approval_eligible=all(item.passed for item in constraints),
        schema_version="1.0",
    )
    constraint_bytes = b"".join(item.evidence_hash.encode() for item in constraints)
    return CounterfactualComparison(
        result=result,
        evidence_hashes=ComparisonEvidenceHashes(
            patch_hash=run.patch_hash,
            baseline_manifest_hash=run.baseline_manifest.manifest_hash,
            candidate_manifest_hash=run.candidate_manifest.manifest_hash,
            baseline_trace_hash=run.baseline_trace.trace_hash,
            candidate_trace_hash=run.candidate_trace.trace_hash,
            constraint_set_hash=hashlib.sha256(constraint_bytes).hexdigest(),
        ),
    )


def hash_comparison(comparison: CounterfactualComparison) -> Sha256Hex:
    """Return the complete comparison identity used by policy and approval."""
    return hashlib.sha256(canonical_model_bytes(comparison)).hexdigest()
