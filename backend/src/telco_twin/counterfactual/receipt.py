"""Recomputed simulator provenance receipt unavailable to JSON boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum, unique
from typing import assert_never, final, override

from telco_twin.counterfactual.comparison import (
    CounterfactualComparison,
    CounterfactualMetricError,
    compare_counterfactual,
    hash_comparison,
)
from telco_twin.counterfactual.runner import (
    CounterfactualRejected,
    CounterfactualRun,
    run_counterfactual,
)
from telco_twin.domain._contract import Sha256Hex, StrictContract
from telco_twin.simulator.engine import ManifestIntegrityError


@unique
class ReceiptErrorCode(StrEnum):
    """Stable reasons simulator provenance cannot be sealed."""

    EMPTY_TRACE = "simulation-empty-trace"
    RUN_CHANGED = "simulation-run-changed"
    COMPARISON_CHANGED = "simulation-comparison-changed"
    MANIFEST_INVALID = "simulation-manifest-invalid"


@dataclass(frozen=True, slots=True)
class ReceiptRejected:
    """Fail-closed simulator provenance result."""

    code: ReceiptErrorCode


class SimulationReceiptEvidence(StrictContract):
    """Serializable identities independently supported by a sealed receipt."""

    patch_hash: Sha256Hex
    simulation_hash: Sha256Hex
    baseline_manifest_hash: Sha256Hex
    candidate_manifest_hash: Sha256Hex
    baseline_trace_hash: Sha256Hex
    candidate_trace_hash: Sha256Hex
    baseline_event_count: int
    candidate_event_count: int


@dataclass(frozen=True, slots=True)
class _ReceiptIssuer:
    """Module-identity marker preventing ordinary direct receipt construction."""


_RECEIPT_ISSUER = _ReceiptIssuer()


@dataclass(frozen=True, slots=True)
class ReceiptCreationError(Exception):
    """A caller attempted to construct provenance outside verification."""

    @override
    def __str__(self) -> str:
        return "simulation-receipt-construction-forbidden"


@final
class SimulationReceipt:
    """Internal capability retaining the exact run and comparison it proves."""

    __slots__ = ("_comparison", "_evidence", "_run")

    def __init__(
        self,
        issuer: _ReceiptIssuer,
        run: CounterfactualRun,
        comparison: CounterfactualComparison,
    ) -> None:
        """Accept construction only from this module's recomputation path."""
        if issuer is not _RECEIPT_ISSUER:
            raise ReceiptCreationError
        self._run = run
        self._comparison = comparison
        self._evidence = SimulationReceiptEvidence(
            patch_hash=run.patch_hash,
            simulation_hash=hash_comparison(comparison),
            baseline_manifest_hash=run.baseline_manifest.manifest_hash,
            candidate_manifest_hash=run.candidate_manifest.manifest_hash,
            baseline_trace_hash=run.baseline_trace.trace_hash,
            candidate_trace_hash=run.candidate_trace.trace_hash,
            baseline_event_count=len(run.baseline_trace.events),
            candidate_event_count=len(run.candidate_trace.events),
        )

    @property
    def evidence(self) -> SimulationReceiptEvidence:
        """Return detached serializable receipt identities."""
        return self._evidence

    @property
    def run(self) -> CounterfactualRun:
        """Return the immutable run retained for later revalidation."""
        return self._run

    @property
    def comparison(self) -> CounterfactualComparison:
        """Return the immutable comparison retained for later revalidation."""
        return self._comparison


type ReceiptResult = SimulationReceipt | ReceiptRejected


def _verified_run(run: CounterfactualRun) -> CounterfactualRun | ReceiptRejected:
    traces = (run.baseline_trace, run.candidate_trace, run.replay_trace)
    if any(not trace.events for trace in traces):
        return ReceiptRejected(ReceiptErrorCode.EMPTY_TRACE)
    try:
        expected = run_counterfactual(run.baseline_manifest, run.patch)
    except ManifestIntegrityError:
        return ReceiptRejected(ReceiptErrorCode.MANIFEST_INVALID)
    match expected:
        case CounterfactualRejected():
            return ReceiptRejected(ReceiptErrorCode.RUN_CHANGED)
        case CounterfactualRun():
            return expected if expected == run else ReceiptRejected(ReceiptErrorCode.RUN_CHANGED)
        case _:
            assert_never(expected)


def _verified_comparison(
    run: CounterfactualRun,
    comparison: CounterfactualComparison,
) -> CounterfactualComparison | ReceiptRejected:
    try:
        expected = compare_counterfactual(run, comparison.result.simulation_id)
    except CounterfactualMetricError:
        return ReceiptRejected(ReceiptErrorCode.COMPARISON_CHANGED)
    return (
        expected if expected == comparison else ReceiptRejected(ReceiptErrorCode.COMPARISON_CHANGED)
    )


def verify_counterfactual(
    run: CounterfactualRun,
    comparison: CounterfactualComparison,
) -> ReceiptResult:
    """Rerun and recompare all simulator evidence before sealing provenance."""
    run_result = _verified_run(run)
    match run_result:
        case ReceiptRejected():
            return run_result
        case CounterfactualRun():
            comparison_result = _verified_comparison(run_result, comparison)
        case _:
            assert_never(run_result)
    match comparison_result:
        case ReceiptRejected():
            return comparison_result
        case CounterfactualComparison():
            return SimulationReceipt(_RECEIPT_ISSUER, run_result, comparison_result)
        case _:
            assert_never(comparison_result)


def revalidate_counterfactual_receipt(receipt: SimulationReceipt) -> ReceiptResult:
    """Recompute a retained receipt to detect later alias mutation."""
    return verify_counterfactual(receipt.run, receipt.comparison)
