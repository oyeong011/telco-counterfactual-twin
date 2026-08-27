"""End-to-end behavior coverage for every typed remediation operation."""

from dataclasses import dataclass

import pytest

from telco_twin.counterfactual.comparison import compare_counterfactual
from telco_twin.counterfactual.runner import CounterfactualRun, run_counterfactual
from telco_twin.data.synthetic import generate_manifest
from telco_twin.domain._contract import JsonScalar
from telco_twin.domain.intervention import (
    BlastRadius,
    PatchChange,
    PatchOperation,
    TargetKind,
    TypedPatch,
)


@dataclass(frozen=True, slots=True)
class _Variant:
    operation: PatchOperation
    target_kind: TargetKind
    target_id: str
    parameter: str
    value: JsonScalar
    attribute: str | None
    metric_name: str
    unit: str


VARIANTS = (
    _Variant(
        PatchOperation.ADJUST_RADIO_CAPACITY,
        TargetKind.CELL,
        "cell-0001",
        "capacity_ues",
        230,
        "capacity_ues",
        "capacity-ues",
        "count",
    ),
    _Variant(
        PatchOperation.RESTORE_BACKHAUL_CAPACITY,
        TargetKind.BACKHAUL,
        "backhaul-0001",
        "capacity_mbps",
        8_000.0,
        "capacity_mbps",
        "capacity-mbps",
        "mbps",
    ),
    _Variant(
        PatchOperation.SCALE_UPF_CAPACITY,
        TargetKind.UPF,
        "upf-0001",
        "capacity_units",
        200,
        "capacity_units",
        "capacity-units",
        "count",
    ),
    _Variant(
        operation=PatchOperation.CORRECT_NEIGHBOR_RELATION,
        target_kind=TargetKind.NEIGHBOR_RELATION,
        target_id="cell-0001",
        parameter="relation_valid",
        value=True,
        attribute=None,
        metric_name="relation-valid",
        unit="boolean",
    ),
    _Variant(
        PatchOperation.REBALANCE_SLICE_WEIGHT,
        TargetKind.SLICE,
        "slice-embb",
        "scheduler_weight",
        90,
        "scheduler_weight",
        "scheduler-weight",
        "count",
    ),
    _Variant(
        operation=PatchOperation.IGNORE_UNTRUSTED_ALARM,
        target_kind=TargetKind.ALARM,
        target_id="cell-0001",
        parameter="alarm_ignored",
        value=True,
        attribute=None,
        metric_name="alarm-ignored",
        unit="boolean",
    ),
)


def _patch(variant: _Variant) -> TypedPatch:
    manifest = generate_manifest(67)
    return TypedPatch(
        patch_id=f"patch-{variant.operation.value}",
        scenario_id=manifest.scenario.scenario_id,
        base_topology_hash=manifest.topology_hash,
        changes=(
            PatchChange(
                target_id=variant.target_id,
                target_kind=variant.target_kind,
                operation=variant.operation,
                parameters={variant.parameter: variant.value},
            ),
        ),
        blast_radius=BlastRadius(max_cells=1, max_ue_cohorts=1, max_slices=1),
        proposed_at="2026-08-27T00:00:00Z",
        schema_version="1.0",
    )


@pytest.mark.parametrize(
    "variant",
    VARIANTS,
    ids=[variant.operation.value for variant in VARIANTS],
)
def test_each_remediation_variant_changes_only_candidate_evidence(
    variant: _Variant,
) -> None:
    # Given: one accepted operation-specific patch over the same immutable baseline.
    manifest = generate_manifest(67)
    baseline_json = manifest.model_dump_json()
    # When: the real fork, simulator, and comparison run end to end.
    outcome = run_counterfactual(manifest, _patch(variant))
    assert isinstance(outcome, CounterfactualRun)
    comparison = compare_counterfactual(outcome, f"simulation-{variant.operation.value}")
    # Then: baseline/replay identities and evidence hashes remain auditable.
    assert manifest.model_dump_json() == baseline_json
    assert outcome.baseline_state_hash_before == outcome.baseline_state_hash_after
    assert outcome.candidate_trace.trace_hash == outcome.replay_trace.trace_hash
    assert outcome.baseline_trace.trace_hash != outcome.candidate_trace.trace_hash
    assert comparison.evidence_hashes.patch_hash == outcome.patch_hash
    assert comparison.evidence_hashes.baseline_trace_hash == outcome.baseline_trace.trace_hash
    assert comparison.evidence_hashes.candidate_trace_hash == outcome.candidate_trace.trace_hash
    metric = comparison.result.metric_deltas[0]
    assert metric.metric_name == variant.metric_name
    assert metric.unit == variant.unit
    assert metric.candidate != metric.baseline
    # And: each operation reaches its real manifest mutation surface.
    if variant.attribute is not None:
        node = next(
            item
            for item in outcome.candidate_manifest.topology.nodes
            if item.node_id == variant.target_id
        )
        assert node.attributes[variant.attribute] == variant.value
    elif variant.operation is PatchOperation.CORRECT_NEIGHBOR_RELATION:
        change = outcome.candidate_manifest.topology.config_history[-1].changes
        assert change["relation_valid"] is True
        assert change["target_ref"] == variant.target_id
    else:
        assert outcome.candidate_manifest.scenario.parameters["alarm_ignored"] is True
