"""Machine-checkable evidence constraints for completed candidate forks."""

from __future__ import annotations

import hashlib
from enum import StrEnum, unique
from typing import TYPE_CHECKING, assert_never

from telco_twin.counterfactual.patches import hash_patch
from telco_twin.domain.simulation_result import ConstraintResult

if TYPE_CHECKING:
    from telco_twin.counterfactual.runner import CounterfactualRun


@unique
class ConstraintCode(StrEnum):
    """Closed local constraints required before policy evaluation."""

    PATCH_BOUNDED = "patch-bounded"
    BASELINE_IMMUTABLE = "baseline-immutable"
    REPLAY_DETERMINISTIC = "replay-deterministic"


def _evidence_hash(code: ConstraintCode, *values: str) -> str:
    message = b"telco-twin/constraint/v1\0" + code.value.encode()
    for value in values:
        message += b"\0" + value.encode()
    return hashlib.sha256(message).hexdigest()


def _constraint(run: CounterfactualRun, code: ConstraintCode) -> ConstraintResult:
    match code:
        case ConstraintCode.PATCH_BOUNDED:
            passed = hash_patch(run.patch) == run.patch_hash
            values = (run.patch_hash, run.patch.base_topology_hash)
        case ConstraintCode.BASELINE_IMMUTABLE:
            passed = run.baseline_state_hash_before == run.baseline_state_hash_after
            values = (run.baseline_state_hash_before, run.baseline_state_hash_after)
        case ConstraintCode.REPLAY_DETERMINISTIC:
            passed = run.candidate_trace.trace_hash == run.replay_trace.trace_hash
            values = (run.candidate_trace.trace_hash, run.replay_trace.trace_hash)
        case _:
            assert_never(code)
    return ConstraintResult(
        constraint_code=code.value,
        passed=passed,
        evidence_hash=_evidence_hash(code, *values),
    )


def build_constraint_results(run: CounterfactualRun) -> tuple[ConstraintResult, ...]:
    """Evaluate every local constraint in stable enum order."""
    return tuple(_constraint(run, code) for code in ConstraintCode)
