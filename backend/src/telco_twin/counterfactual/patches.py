"""Closed remediation patch assessment and canonical identity."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum, unique
from typing import TYPE_CHECKING, Final, assert_never

from telco_twin.domain.canonical import canonical_model_bytes
from telco_twin.domain.intervention import PatchChange, PatchOperation, TargetKind, TypedPatch
from telco_twin.domain.topology import NodeKind

if TYPE_CHECKING:
    from telco_twin.data.synthetic import SimulationManifest
    from telco_twin.domain._contract import JsonScalar, Sha256Hex
    from telco_twin.domain.topology import TopologyNode


@unique
class PatchRejectionCode(StrEnum):
    """Stable reasons a candidate fork cannot be created."""

    SCENARIO = "scenario-binding-mismatch"
    BASELINE_HASH = "baseline-hash-mismatch"
    DUPLICATE_TARGET = "duplicate-patch-target"
    UNKNOWN_TARGET = "unknown-patch-target"
    TARGET_KIND = "target-kind-mismatch"
    OPERATION_TARGET = "operation-target-mismatch"
    PARAMETERS = "unsupported-patch-parameters"
    PARAMETER_TYPE = "patch-parameter-type"
    PARAMETER_RANGE = "patch-parameter-range"
    BLAST_RADIUS = "blast-radius-exceeded"


@dataclass(frozen=True, slots=True)
class PatchAccepted:
    """Canonical patch identity accepted for a simulation-only fork."""

    patch_hash: Sha256Hex


@dataclass(frozen=True, slots=True)
class PatchRejected:
    """Fail-closed patch assessment."""

    code: PatchRejectionCode


type PatchAssessment = PatchAccepted | PatchRejected


@dataclass(frozen=True, slots=True)
class _OperationSpec:
    target_kind: TargetKind
    parameter_name: str
    minimum: float | None
    maximum: float | None
    integer_only: bool
    required_boolean: bool | None = None


@dataclass(frozen=True, slots=True)
class _ParameterCandidate:
    value: JsonScalar
    spec: _OperationSpec


CELL_SPEC: Final = _OperationSpec(
    target_kind=TargetKind.CELL,
    parameter_name="capacity_ues",
    minimum=1,
    maximum=1000,
    integer_only=True,
)
BACKHAUL_SPEC: Final = _OperationSpec(
    target_kind=TargetKind.BACKHAUL,
    parameter_name="capacity_mbps",
    minimum=1,
    maximum=1_000_000,
    integer_only=False,
)
UPF_SPEC: Final = _OperationSpec(
    target_kind=TargetKind.UPF,
    parameter_name="capacity_units",
    minimum=1,
    maximum=10_000,
    integer_only=True,
)
NEIGHBOR_SPEC: Final = _OperationSpec(
    target_kind=TargetKind.NEIGHBOR_RELATION,
    parameter_name="relation_valid",
    minimum=None,
    maximum=None,
    integer_only=False,
    required_boolean=True,
)
SLICE_SPEC: Final = _OperationSpec(
    target_kind=TargetKind.SLICE,
    parameter_name="scheduler_weight",
    minimum=1,
    maximum=100,
    integer_only=True,
)
ALARM_SPEC: Final = _OperationSpec(
    target_kind=TargetKind.ALARM,
    parameter_name="alarm_ignored",
    minimum=None,
    maximum=None,
    integer_only=False,
    required_boolean=True,
)


def hash_patch(patch: TypedPatch) -> Sha256Hex:
    """Return the SHA-256 identity of the complete canonical typed patch."""
    return hashlib.sha256(canonical_model_bytes(patch)).hexdigest()


def _operation_spec(change: PatchChange) -> _OperationSpec:
    match change.operation:
        case PatchOperation.ADJUST_RADIO_CAPACITY:
            spec = CELL_SPEC
        case PatchOperation.RESTORE_BACKHAUL_CAPACITY:
            spec = BACKHAUL_SPEC
        case PatchOperation.SCALE_UPF_CAPACITY:
            spec = UPF_SPEC
        case PatchOperation.CORRECT_NEIGHBOR_RELATION:
            spec = NEIGHBOR_SPEC
        case PatchOperation.REBALANCE_SLICE_WEIGHT:
            spec = SLICE_SPEC
        case PatchOperation.IGNORE_UNTRUSTED_ALARM:
            spec = ALARM_SPEC
        case _:  # pragma: no cover - exhaustive enum
            assert_never(change.operation)
    return spec


def _target_kind(node: TopologyNode) -> TargetKind | None:
    result: TargetKind | None
    match node.kind:
        case NodeKind.CELL:
            result = TargetKind.CELL
        case NodeKind.BACKHAUL:
            result = TargetKind.BACKHAUL
        case NodeKind.UPF:
            result = TargetKind.UPF
        case NodeKind.SLICE:
            result = TargetKind.SLICE
        case NodeKind.GNB | NodeKind.UE_COHORT | NodeKind.AMF | NodeKind.SMF:
            result = None
        case _:  # pragma: no cover - exhaustive enum
            assert_never(node.kind)
    return result


def _parameter_rejection(candidate: _ParameterCandidate) -> PatchRejectionCode | None:
    rejection: PatchRejectionCode | None = None
    numeric: float | None = None
    if candidate.spec.required_boolean is not None:
        if candidate.value is not candidate.spec.required_boolean:
            rejection = PatchRejectionCode.PARAMETER_RANGE
    else:
        match candidate.value:
            case bool() | str() | None:
                rejection = PatchRejectionCode.PARAMETER_TYPE
            case int() as number:
                numeric = float(number)
            case float() as number:
                rejection = (
                    PatchRejectionCode.PARAMETER_TYPE if candidate.spec.integer_only else None
                )
                numeric = number
            case _:  # pragma: no cover - exhaustive scalar union
                assert_never(candidate.value)
        if rejection is None and numeric is not None:
            if candidate.spec.minimum is None or candidate.spec.maximum is None:
                rejection = PatchRejectionCode.PARAMETER_TYPE
            elif not candidate.spec.minimum <= numeric <= candidate.spec.maximum:
                rejection = PatchRejectionCode.PARAMETER_RANGE
    return rejection


def _one_change_rejection(
    change: PatchChange,
    manifest: SimulationManifest,
) -> PatchRejectionCode | None:
    spec = _operation_spec(change)
    if change.target_kind is not spec.target_kind:
        return PatchRejectionCode.OPERATION_TARGET
    node = next(
        (item for item in manifest.topology.nodes if item.node_id == change.target_id),
        None,
    )
    virtual_target = change.target_kind in {
        TargetKind.NEIGHBOR_RELATION,
        TargetKind.ALARM,
    }
    if virtual_target and change.target_id not in manifest.scenario.target_ids:
        return PatchRejectionCode.UNKNOWN_TARGET
    if not virtual_target and node is None:
        return PatchRejectionCode.UNKNOWN_TARGET
    if not virtual_target and node is not None and _target_kind(node) is not change.target_kind:
        return PatchRejectionCode.TARGET_KIND
    if set(change.parameters) != {spec.parameter_name}:
        return PatchRejectionCode.PARAMETERS
    return _parameter_rejection(
        _ParameterCandidate(value=change.parameters[spec.parameter_name], spec=spec)
    )


def _change_rejection(
    patch: TypedPatch,
    manifest: SimulationManifest,
) -> PatchRejectionCode | None:
    for change in patch.changes:
        rejection = _one_change_rejection(change, manifest)
        if rejection is not None:
            return rejection
    return None


def _radius_exceeded(patch: TypedPatch, manifest: SimulationManifest) -> bool:
    cell_ids = {item.target_id for item in patch.changes if item.target_kind is TargetKind.CELL}
    slice_ids = {item.target_id for item in patch.changes if item.target_kind is TargetKind.SLICE}
    node_kinds = {node.node_id: node.kind for node in manifest.topology.nodes}
    cohort_ids = {
        link.source_id
        for link in manifest.topology.links
        if link.target_id in cell_ids and node_kinds[link.source_id] is NodeKind.UE_COHORT
    }
    return (
        len(cell_ids) > patch.blast_radius.max_cells
        or len(cohort_ids) > patch.blast_radius.max_ue_cohorts
        or len(slice_ids) > patch.blast_radius.max_slices
    )


def assess_patch(patch: TypedPatch, manifest: SimulationManifest) -> PatchAssessment:
    """Check all closed patch bounds before any simulator work begins."""
    rejection: PatchRejectionCode | None = None
    if patch.scenario_id != manifest.scenario.scenario_id:
        rejection = PatchRejectionCode.SCENARIO
    elif patch.base_topology_hash != manifest.topology_hash:
        rejection = PatchRejectionCode.BASELINE_HASH
    else:
        target_ids = tuple(change.target_id for change in patch.changes)
        if len(set(target_ids)) != len(target_ids):
            rejection = PatchRejectionCode.DUPLICATE_TARGET
        else:
            rejection = _change_rejection(patch, manifest)
            if rejection is None and _radius_exceeded(patch, manifest):
                rejection = PatchRejectionCode.BLAST_RADIUS
    return PatchAccepted(hash_patch(patch)) if rejection is None else PatchRejected(rejection)
