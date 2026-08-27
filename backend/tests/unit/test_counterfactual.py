"""Immutable deterministic counterfactual runner tests."""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from telco_twin.counterfactual.comparison import compare_counterfactual, hash_comparison
from telco_twin.counterfactual.patches import PatchAccepted
from telco_twin.counterfactual.runner import CounterfactualRun, run_counterfactual
from telco_twin.data.synthetic import generate_manifest
from telco_twin.domain.intervention import (
    BlastRadius,
    PatchChange,
    PatchOperation,
    TargetKind,
    TypedPatch,
)
from telco_twin.simulator.engine import ManifestIntegrityError, run_simulation


def _patch(capacity_ues: int = 220) -> TypedPatch:
    manifest = generate_manifest(53)
    return TypedPatch(
        patch_id=f"patch-capacity-{capacity_ues}",
        scenario_id=manifest.scenario.scenario_id,
        base_topology_hash=manifest.topology_hash,
        changes=(
            PatchChange(
                target_id="cell-0001",
                target_kind=TargetKind.CELL,
                operation=PatchOperation.ADJUST_RADIO_CAPACITY,
                parameters={"capacity_ues": capacity_ues},
            ),
        ),
        blast_radius=BlastRadius(max_cells=1, max_ue_cohorts=1, max_slices=1),
        proposed_at="2026-08-27T00:00:00Z",
        schema_version="1.0",
    )


def test_same_patch_and_seed_produce_identical_candidate_and_comparison_hashes() -> None:
    # Given: one immutable baseline and one canonical patch.
    manifest = generate_manifest(53)
    patch = _patch()
    # When: independent counterfactual forks are run and compared.
    first = run_counterfactual(manifest, patch)
    second = run_counterfactual(manifest, patch)
    assert isinstance(first, CounterfactualRun)
    assert isinstance(second, CounterfactualRun)
    first_comparison = compare_counterfactual(first, "simulation-0001")
    second_comparison = compare_counterfactual(second, "simulation-0001")
    # Then: all candidate and comparison evidence hashes are deterministic.
    assert first.candidate_trace.trace_hash == second.candidate_trace.trace_hash
    assert first.candidate_manifest.manifest_hash == second.candidate_manifest.manifest_hash
    assert hash_comparison(first_comparison) == hash_comparison(second_comparison)


@given(seed=st.integers(min_value=0, max_value=1_000_000))
@settings(max_examples=16, deadline=None)
def test_counterfactual_determinism_holds_across_seed_property(seed: int) -> None:
    # Given: an arbitrary valid synthetic seed and one baseline-bound cell patch.
    manifest = generate_manifest(seed)
    patch = TypedPatch(
        patch_id="patch-property",
        scenario_id=manifest.scenario.scenario_id,
        base_topology_hash=manifest.topology_hash,
        changes=(
            PatchChange(
                target_id="cell-0001",
                target_kind=TargetKind.CELL,
                operation=PatchOperation.ADJUST_RADIO_CAPACITY,
                parameters={"capacity_ues": 240},
            ),
        ),
        blast_radius=BlastRadius(max_cells=1, max_ue_cohorts=1, max_slices=1),
        proposed_at="2026-08-27T00:00:00Z",
        schema_version="1.0",
    )
    # When: two isolated candidate forks execute.
    first = run_counterfactual(manifest, patch)
    second = run_counterfactual(manifest, patch)
    # Then: every seed has one deterministic candidate trace identity.
    assert isinstance(first, CounterfactualRun)
    assert isinstance(second, CounterfactualRun)
    assert first.candidate_trace.trace_hash == second.candidate_trace.trace_hash


def test_counterfactual_fork_preserves_baseline_nested_state_and_trace_hash() -> None:
    # Given: a baseline with a previously observed trace and nested node attributes.
    manifest = generate_manifest(53)
    trace_before = run_simulation(manifest)
    attributes_before = tuple(dict(node.attributes) for node in manifest.topology.nodes)
    # When: a candidate patch runs in a fork.
    outcome = run_counterfactual(manifest, _patch())
    # Then: the caller-owned baseline remains byte/hash identical.
    assert isinstance(outcome, CounterfactualRun)
    assert run_simulation(manifest).trace_hash == trace_before.trace_hash
    assert tuple(dict(node.attributes) for node in manifest.topology.nodes) == attributes_before
    assert outcome.baseline_trace.trace_hash == trace_before.trace_hash
    assert outcome.candidate_trace.trace_hash != trace_before.trace_hash


def test_changed_patch_changes_candidate_without_changing_baseline() -> None:
    # Given: one baseline and two different allowed capacity values.
    manifest = generate_manifest(53)
    # When: both candidates are forked independently.
    first = run_counterfactual(manifest, _patch(220))
    second = run_counterfactual(manifest, _patch(221))
    # Then: only candidate evidence changes.
    assert isinstance(first, CounterfactualRun)
    assert isinstance(second, CounterfactualRun)
    assert first.baseline_trace.trace_hash == second.baseline_trace.trace_hash
    assert first.candidate_trace.trace_hash != second.candidate_trace.trace_hash


def test_comparison_exposes_metric_constraint_and_evidence_hashes() -> None:
    # Given: a completed deterministic candidate fork.
    outcome = run_counterfactual(generate_manifest(53), _patch())
    assert isinstance(outcome, CounterfactualRun)
    # When: the run is compared.
    comparison = compare_counterfactual(outcome, "simulation-0001")
    # Then: deltas, constraints, and independently verifiable hashes are present.
    assert (
        comparison.result.metric_deltas[0].baseline != comparison.result.metric_deltas[0].candidate
    )
    assert all(item.passed for item in comparison.result.constraints)
    assert comparison.result.approval_eligible is True
    assert comparison.evidence_hashes.patch_hash == outcome.patch_hash
    assert comparison.evidence_hashes.baseline_trace_hash == outcome.baseline_trace.trace_hash
    assert comparison.evidence_hashes.candidate_trace_hash == outcome.candidate_trace.trace_hash
    assert len(hash_comparison(comparison)) == 64


def test_runner_returns_typed_rejection_before_dirty_baseline_can_run() -> None:
    # Given: a patch that does not bind the baseline hash.
    manifest = generate_manifest(53)
    patch = _patch().model_copy(update={"base_topology_hash": "0" * 64})
    # When: a counterfactual run is requested.
    outcome = run_counterfactual(manifest, patch)
    # Then: no baseline or candidate trace is exposed.
    assert not isinstance(outcome, CounterfactualRun)
    assert not isinstance(outcome.assessment, PatchAccepted)


def test_runner_rejects_nested_dirty_baseline_before_candidate_trace() -> None:
    # Given: a manifest whose nested topology changed after its hashes were committed.
    manifest = generate_manifest(53)
    manifest.topology.nodes[0].attributes["capacity_ues"] = 999
    # When: a correctly bound patch attempts to cross simulator integrity.
    with pytest.raises(ManifestIntegrityError, match="simulation-manifest"):
        _ = run_counterfactual(manifest, _patch())
    # Then: no candidate trace can be returned from dirty baseline state.
