"""Typed, bounded simulation-only intervention contract."""

from __future__ import annotations

from enum import StrEnum, unique
from typing import Annotated, Self

from pydantic import Field, model_validator

from ._contract import (
    ContractId,
    RootContract,
    SafeProperties,
    Sha256Hex,
    StrictContract,
    UtcTimestamp,
    fail_validation,
)


@unique
class TargetKind(StrEnum):
    """Closed synthetic targets that a candidate patch may reference."""

    CELL = "cell"
    BACKHAUL = "backhaul"
    UPF = "upf"
    NEIGHBOR_RELATION = "neighbor-relation"
    SLICE = "slice"
    ALARM = "alarm"


@unique
class PatchOperation(StrEnum):
    """Simulation-only remediation operations."""

    ADJUST_RADIO_CAPACITY = "adjust-radio-capacity"
    RESTORE_BACKHAUL_CAPACITY = "restore-backhaul-capacity"
    SCALE_UPF_CAPACITY = "scale-upf-capacity"
    CORRECT_NEIGHBOR_RELATION = "correct-neighbor-relation"
    REBALANCE_SLICE_WEIGHT = "rebalance-slice-weight"
    IGNORE_UNTRUSTED_ALARM = "ignore-untrusted-alarm"


class PatchChange(StrictContract):
    """One typed candidate change evaluated only in a forked simulation."""

    target_id: ContractId
    target_kind: TargetKind
    operation: PatchOperation
    parameters: SafeProperties


class BlastRadius(StrictContract):
    """Explicit upper bounds for affected synthetic resources."""

    max_cells: Annotated[int, Field(ge=0, le=4)]
    max_ue_cohorts: Annotated[int, Field(ge=0, le=32)]
    max_slices: Annotated[int, Field(ge=0, le=8)]

    @model_validator(mode="after")
    def is_nonzero(self) -> Self:
        """Reject a radius that names no bounded target at all."""
        if self.max_cells + self.max_ue_cohorts + self.max_slices == 0:
            fail_validation("empty_blast_radius", "blast radius cannot be empty")
        return self


class TypedPatch(RootContract):
    """Immutable candidate input used only by a forked simulation."""

    patch_id: ContractId
    scenario_id: ContractId
    base_topology_hash: Sha256Hex
    changes: Annotated[tuple[PatchChange, ...], Field(min_length=1, max_length=16)]
    blast_radius: BlastRadius
    proposed_at: UtcTimestamp
