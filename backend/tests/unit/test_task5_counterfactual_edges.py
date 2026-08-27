"""Behavioral error branches across patch, comparison, runner, and receipts."""

from dataclasses import replace
from enum import StrEnum, unique
from typing import assert_never

import pytest

from telco_twin.counterfactual.comparison import (
    CounterfactualComparison,
    CounterfactualMetricError,
    compare_counterfactual,
)
from telco_twin.counterfactual.patches import (
    PatchRejected,
    PatchRejectionCode,
    assess_patch,
)
from telco_twin.counterfactual.receipt import (
    ReceiptCreationError,
    ReceiptErrorCode,
    ReceiptIssuer,
    ReceiptRejected,
    SimulationReceipt,
    verify_counterfactual,
)
from telco_twin.counterfactual.runner import (
    CounterfactualRejected,
    CounterfactualRun,
    run_counterfactual,
)
from telco_twin.data.synthetic import SimulationManifest, generate_manifest
from telco_twin.domain.intervention import (
    BlastRadius,
    PatchChange,
    PatchOperation,
    TargetKind,
    TypedPatch,
)


def _patch(manifest: SimulationManifest) -> TypedPatch:
    return TypedPatch(
        patch_id="patch-edge-radio",
        scenario_id=manifest.scenario.scenario_id,
        base_topology_hash=manifest.topology_hash,
        changes=(
            PatchChange(
                target_id="cell-0001",
                target_kind=TargetKind.CELL,
                operation=PatchOperation.ADJUST_RADIO_CAPACITY,
                parameters={"capacity_ues": 230},
            ),
        ),
        blast_radius=BlastRadius(max_cells=1, max_ue_cohorts=32, max_slices=1),
        proposed_at="2026-08-27T00:00:00Z",
        schema_version="1.0",
    )


@unique
class _RejectionCase(StrEnum):
    SCENARIO = "scenario"
    DUPLICATE = "duplicate"
    VIRTUAL_UNKNOWN = "virtual-unknown"
    NODE_KIND = "node-kind"
    BOOLEAN = "boolean"
    SCALAR = "scalar"
    RADIUS = "radius"


@pytest.mark.parametrize("case", tuple(_RejectionCase))
def test_patch_rejection_classes_are_reached_by_real_inputs(
    case: _RejectionCase,
) -> None:
    manifest = generate_manifest(67)
    patch = _patch(manifest)
    change = patch.changes[0]
    match case:
        case _RejectionCase.SCENARIO:
            candidate = patch.model_copy(update={"scenario_id": "scenario-other"})
            expected = PatchRejectionCode.SCENARIO
        case _RejectionCase.DUPLICATE:
            candidate = patch.model_copy(update={"changes": (change, change)})
            expected = PatchRejectionCode.DUPLICATE_TARGET
        case _RejectionCase.VIRTUAL_UNKNOWN:
            candidate = patch.model_copy(
                update={
                    "changes": (
                        change.model_copy(
                            update={
                                "target_id": "cell-unknown",
                                "target_kind": TargetKind.NEIGHBOR_RELATION,
                                "operation": PatchOperation.CORRECT_NEIGHBOR_RELATION,
                                "parameters": {"relation_valid": True},
                            }
                        ),
                    )
                }
            )
            expected = PatchRejectionCode.UNKNOWN_TARGET
        case _RejectionCase.NODE_KIND:
            candidate = patch.model_copy(
                update={"changes": (change.model_copy(update={"target_id": "gnb-0001"}),)}
            )
            expected = PatchRejectionCode.TARGET_KIND
        case _RejectionCase.BOOLEAN:
            candidate = patch.model_copy(
                update={
                    "changes": (
                        change.model_copy(
                            update={
                                "target_kind": TargetKind.NEIGHBOR_RELATION,
                                "operation": PatchOperation.CORRECT_NEIGHBOR_RELATION,
                                "parameters": {"relation_valid": False},
                            }
                        ),
                    )
                }
            )
            expected = PatchRejectionCode.PARAMETER_RANGE
        case _RejectionCase.SCALAR:
            candidate = patch.model_copy(
                update={
                    "changes": (change.model_copy(update={"parameters": {"capacity_ues": "x"}}),)
                }
            )
            expected = PatchRejectionCode.PARAMETER_TYPE
        case _RejectionCase.RADIUS:
            second = change.model_copy(
                update={"target_id": "cell-0002", "parameters": {"capacity_ues": 220}}
            )
            candidate = patch.model_copy(update={"changes": (change, second)})
            expected = PatchRejectionCode.BLAST_RADIUS
        case _:
            assert_never(case)
    assert assess_patch(candidate, manifest) == PatchRejected(expected)


def _run_and_comparison() -> tuple[CounterfactualRun, CounterfactualComparison]:
    manifest = generate_manifest(67)
    outcome = run_counterfactual(manifest, _patch(manifest))
    assert isinstance(outcome, CounterfactualRun)
    return outcome, compare_counterfactual(outcome, "simulation-edge")


def test_invalid_patch_returns_rejected_without_simulation() -> None:
    manifest = generate_manifest(67)
    outcome = run_counterfactual(
        manifest,
        _patch(manifest).model_copy(update={"base_topology_hash": "0" * 64}),
    )
    assert isinstance(outcome, CounterfactualRejected)
    assert outcome.assessment.code is PatchRejectionCode.BASELINE_HASH


def test_non_numeric_candidate_metric_fails_closed() -> None:
    run, _ = _run_and_comparison()
    nodes = tuple(
        node.model_copy(update={"attributes": {**node.attributes, "capacity_ues": "bad"}})
        if node.node_id == "cell-0001"
        else node
        for node in run.candidate_manifest.topology.nodes
    )
    topology = run.candidate_manifest.topology.model_copy(update={"nodes": nodes})
    candidate = run.candidate_manifest.model_copy(update={"topology": topology})
    with pytest.raises(CounterfactualMetricError):
        _ = compare_counterfactual(
            replace(run, candidate_manifest=candidate),
            "simulation-nonnumeric",
        )


def test_receipt_rejects_external_construction_empty_trace_and_changed_run() -> None:
    run, comparison = _run_and_comparison()
    with pytest.raises(ReceiptCreationError):
        _ = SimulationReceipt(ReceiptIssuer(), run, comparison)
    empty = replace(run.baseline_trace, events=())
    assert verify_counterfactual(
        replace(run, baseline_trace=empty),
        comparison,
    ) == ReceiptRejected(ReceiptErrorCode.EMPTY_TRACE)
    changed = replace(run, baseline_state_hash_after="0" * 64)
    assert verify_counterfactual(changed, comparison) == ReceiptRejected(
        ReceiptErrorCode.RUN_CHANGED
    )
    invalid_patch = run.patch.model_copy(update={"base_topology_hash": "0" * 64})
    assert verify_counterfactual(
        replace(run, patch=invalid_patch),
        comparison,
    ) == ReceiptRejected(ReceiptErrorCode.RUN_CHANGED)


def test_receipt_rejects_dirty_manifest_and_changed_comparison() -> None:
    run, comparison = _run_and_comparison()
    dirty = SimulationManifest.model_validate_json(run.baseline_manifest.model_dump_json())
    dirty.topology.nodes[0].attributes["capacity_ues"] = 999
    assert verify_counterfactual(
        replace(run, baseline_manifest=dirty),
        comparison,
    ) == ReceiptRejected(ReceiptErrorCode.MANIFEST_INVALID)
    first = comparison.result.metric_deltas[0]
    result = comparison.result.model_copy(
        update={"metric_deltas": (first.model_copy(update={"candidate": first.candidate + 1}),)}
    )
    changed = comparison.model_copy(update={"result": result})
    assert verify_counterfactual(run, changed) == ReceiptRejected(
        ReceiptErrorCode.COMPARISON_CHANGED
    )
