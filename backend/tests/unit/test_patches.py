"""Typed remediation patch boundary tests."""

import pytest

from telco_twin.counterfactual.patches import (
    PatchAccepted,
    PatchRejected,
    PatchRejectionCode,
    assess_patch,
    hash_patch,
)
from telco_twin.data.synthetic import generate_manifest
from telco_twin.domain.intervention import (
    BlastRadius,
    PatchChange,
    PatchOperation,
    TargetKind,
    TypedPatch,
)


def _patch(
    *,
    target_id: str = "cell-0001",
    target_kind: TargetKind = TargetKind.CELL,
    operation: PatchOperation = PatchOperation.ADJUST_RADIO_CAPACITY,
    parameters: dict[str, str | int | float | bool | None] | None = None,
) -> TypedPatch:
    manifest = generate_manifest(41)
    return TypedPatch(
        patch_id="patch-0001",
        scenario_id=manifest.scenario.scenario_id,
        base_topology_hash=manifest.topology_hash,
        changes=(
            PatchChange(
                target_id=target_id,
                target_kind=target_kind,
                operation=operation,
                parameters={"capacity_ues": 200} if parameters is None else parameters,
            ),
        ),
        blast_radius=BlastRadius(max_cells=1, max_ue_cohorts=1, max_slices=1),
        proposed_at="2026-08-27T00:00:00Z",
        schema_version="1.0",
    )


def test_patch_is_accepted_when_operation_parameters_and_radius_are_bounded() -> None:
    # Given: a patch bound to an existing cell and the exact baseline topology hash.
    manifest = generate_manifest(41)
    patch = _patch()
    # When: the typed patch is assessed.
    result = assess_patch(patch, manifest)
    # Then: its canonical hash is exposed as accepted evidence.
    assert result == PatchAccepted(patch_hash=hash_patch(patch))


@pytest.mark.parametrize(
    ("operation", "target_kind", "target_id", "parameters"),
    [
        (PatchOperation.ADJUST_RADIO_CAPACITY, TargetKind.CELL, "cell-0001", {"capacity_ues": 200}),
        (
            PatchOperation.RESTORE_BACKHAUL_CAPACITY,
            TargetKind.BACKHAUL,
            "backhaul-0001",
            {"capacity_mbps": 8000.0},
        ),
        (
            PatchOperation.SCALE_UPF_CAPACITY,
            TargetKind.UPF,
            "upf-0001",
            {"capacity_units": 160},
        ),
        (
            PatchOperation.REBALANCE_SLICE_WEIGHT,
            TargetKind.SLICE,
            "slice-embb",
            {"scheduler_weight": 60},
        ),
        (
            PatchOperation.CORRECT_NEIGHBOR_RELATION,
            TargetKind.NEIGHBOR_RELATION,
            "cell-0001",
            {"relation_valid": True},
        ),
        (
            PatchOperation.IGNORE_UNTRUSTED_ALARM,
            TargetKind.ALARM,
            "cell-0001",
            {"alarm_ignored": True},
        ),
    ],
)
def test_each_topology_operation_has_one_closed_parameter_contract(
    operation: PatchOperation,
    target_kind: TargetKind,
    target_id: str,
    parameters: dict[str, str | int | float | bool | None],
) -> None:
    # Given: one operation with only its declared target kind and parameter.
    manifest = generate_manifest(41)
    patch = _patch(
        target_id=target_id,
        target_kind=target_kind,
        operation=operation,
        parameters=parameters,
    )
    # When: the operation is assessed.
    result = assess_patch(patch, manifest)
    # Then: the closed operation is accepted.
    assert isinstance(result, PatchAccepted)


@pytest.mark.parametrize(
    ("patch", "expected"),
    [
        (_patch(parameters={"capacity_ues": 200, "arbitrary": 1}), PatchRejectionCode.PARAMETERS),
        (_patch(parameters={"capacity_ues": 1001}), PatchRejectionCode.PARAMETER_RANGE),
        (
            _patch(target_kind=TargetKind.UPF),
            PatchRejectionCode.OPERATION_TARGET,
        ),
        (_patch(target_id="cell-9999"), PatchRejectionCode.UNKNOWN_TARGET),
    ],
)
def test_patch_fails_closed_when_one_typed_boundary_is_unsafe(
    patch: TypedPatch,
    expected: PatchRejectionCode,
) -> None:
    # Given: a patch violating exactly one closed safety boundary.
    manifest = generate_manifest(41)
    # When: the patch is assessed.
    result = assess_patch(patch, manifest)
    # Then: a stable rejection code identifies the failed boundary.
    assert result == PatchRejected(code=expected)


def test_patch_fails_closed_when_baseline_binding_changes() -> None:
    # Given: a valid operation carrying a different topology digest.
    manifest = generate_manifest(41)
    patch = _patch().model_copy(update={"base_topology_hash": "0" * 64})
    # When: the patch is assessed.
    result = assess_patch(patch, manifest)
    # Then: the baseline mismatch is rejected before simulation.
    assert result == PatchRejected(code=PatchRejectionCode.BASELINE_HASH)


def test_patch_fails_closed_when_declared_blast_radius_is_exceeded() -> None:
    # Given: two cell changes with a declared one-cell upper bound.
    manifest = generate_manifest(41)
    first = _patch().changes[0]
    patch = _patch().model_copy(
        update={
            "changes": (
                first,
                first.model_copy(update={"target_id": "cell-0002"}),
            )
        }
    )
    # When: the patch is assessed.
    result = assess_patch(patch, manifest)
    # Then: no unbounded fork is created.
    assert result == PatchRejected(code=PatchRejectionCode.BLAST_RADIUS)
