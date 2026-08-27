"""Immutable counterfactual simulation-result contract."""

from __future__ import annotations

from typing import Annotated, Self

from pydantic import Field, model_validator

from ._contract import (
    ContractId,
    RootContract,
    SafeKey,
    Sha256Hex,
    StrictContract,
    UtcTimestamp,
    fail_validation,
    utc_datetime,
)


class MetricDelta(StrictContract):
    """One bounded baseline-to-candidate metric comparison."""

    metric_name: SafeKey
    baseline: Annotated[float, Field(ge=-1_000_000_000, le=1_000_000_000)]
    candidate: Annotated[float, Field(ge=-1_000_000_000, le=1_000_000_000)]
    unit: SafeKey


class ConstraintResult(StrictContract):
    """Machine-checkable local safety-constraint result."""

    constraint_code: SafeKey
    passed: bool
    evidence_hash: Sha256Hex


class SimulationResult(RootContract):
    """Hashed baseline/candidate comparison eligible only after all constraints pass."""

    simulation_id: ContractId
    scenario_id: ContractId
    patch_hash: Sha256Hex
    baseline_hash: Sha256Hex
    candidate_hash: Sha256Hex
    trace_hash: Sha256Hex
    started_at: UtcTimestamp
    completed_at: UtcTimestamp
    metric_deltas: Annotated[tuple[MetricDelta, ...], Field(min_length=1, max_length=128)]
    constraints: Annotated[tuple[ConstraintResult, ...], Field(min_length=1, max_length=64)]
    approval_eligible: bool

    @model_validator(mode="after")
    def result_is_temporally_and_logically_consistent(self) -> Self:
        """Require ordered timestamps and fail-closed approval eligibility."""
        if utc_datetime(self.completed_at) < utc_datetime(self.started_at):
            fail_validation("simulation_time_order", "simulation completion precedes start")
        if self.approval_eligible and not all(item.passed for item in self.constraints):
            fail_validation(
                "approval_eligibility_inconsistent", "failed constraints cannot be eligible"
            )
        return self
