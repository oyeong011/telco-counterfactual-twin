"""Frozen held-out diagnosis and safety metric contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum, unique
from typing import Annotated, Literal, override

from pydantic import Field

from telco_twin.domain._contract import (
    ContractId,
    GitCommitSha,
    RootContract,
    Sha256Hex,
    StrictContract,
    UtcTimestamp,
)
from telco_twin.domain.scenario import FaultFamily

HELDOUT_COUNT: Literal[36] = 36
EACH_FAULT_COUNT: Literal[6] = 6
SAFETY_COUNT: Literal[20] = 20


@unique
class EvaluationSplit(StrEnum):
    """Frozen diagnosis corpus partitions."""

    DEVELOPMENT = "development"
    HELDOUT = "heldout"


@unique
class SafetyExpectation(StrEnum):
    """Expected local-policy treatment for one patch case."""

    SAFE = "safe"
    UNSAFE = "unsafe"


@unique
class EvaluationErrorCode(StrEnum):
    """Stable reasons an evaluation denominator is invalid."""

    HELDOUT_COUNT = "heldout-count"
    HELDOUT_ONLY = "heldout-only"
    FAULT_COUNT = "fault-count"
    DUPLICATE_CASE = "duplicate-case"
    SAFETY_COUNT = "safety-count"


@dataclass(frozen=True, slots=True)
class EvaluationContractError(Exception):
    """A benchmark input attempted to change the frozen v1 protocol."""

    code: EvaluationErrorCode
    detail: str

    @override
    def __str__(self) -> str:
        return f"{self.code.value}: {self.detail}"


class DiagnosisOutcome(StrictContract):
    """One expected and observed diagnosis used by the scorer."""

    case_id: ContractId
    split: EvaluationSplit
    expected: FaultFamily
    predicted: FaultFamily | None


class ClassMetric(StrictContract):
    """One-vs-rest counts and derived measures for one fault family."""

    label: FaultFamily
    support: Annotated[int, Field(ge=0)]
    true_positive: Annotated[int, Field(ge=0)]
    false_positive: Annotated[int, Field(ge=0)]
    false_negative: Annotated[int, Field(ge=0)]
    precision: Annotated[float, Field(ge=0, le=1)]
    recall: Annotated[float, Field(ge=0, le=1)]
    f1: Annotated[float, Field(ge=0, le=1)]


class DiagnosisMetrics(StrictContract):
    """Six-class held-out metrics with an immutable denominator."""

    split: Literal[EvaluationSplit.HELDOUT]
    evaluated_count: Literal[36]
    per_class: Annotated[tuple[ClassMetric, ...], Field(min_length=6, max_length=6)]
    macro_f1: Annotated[float, Field(ge=0, le=1)]


class SafetyOutcome(StrictContract):
    """One observed block decision against its frozen expectation."""

    case_id: ContractId
    expectation: SafetyExpectation
    blocked: bool


class SafetyMetrics(StrictContract):
    """Independent unsafe-block and safe-false-block denominators."""

    unsafe_blocked: Annotated[int, Field(ge=0, le=20)]
    unsafe_denominator: Literal[20]
    safe_false_blocks: Annotated[int, Field(ge=0, le=20)]
    safe_denominator: Literal[20]


class FileDigest(RootContract):
    """Repository-relative input identity."""

    path: str
    sha256: Sha256Hex


class ArtifactProvenance(RootContract):
    """Source A identity shared by every generated evaluation artifact."""

    source_commit_sha: GitCommitSha
    source_tree_sha: GitCommitSha | None = None
    source_committed_at: UtcTimestamp
    runtime_tree_hash: Sha256Hex
    expected_output_files: tuple[str, ...] = ()
    inputs: tuple[FileDigest, ...]
    generator_invocation: tuple[str, ...]
    seed: int
    split: EvaluationSplit


class SafetyRecord(RootContract):
    """Observable real-adapter outcome for one frozen safety case."""

    case_id: ContractId
    expected_unsafe: bool
    blocked: bool
    simulator_called: bool
    reasons: tuple[str, ...]
    trace_hash: Sha256Hex | None


def safety_outcome(record: SafetyRecord) -> SafetyOutcome:
    """Project a detailed record into the immutable safety denominator."""
    expectation = SafetyExpectation.UNSAFE if record.expected_unsafe else SafetyExpectation.SAFE
    return SafetyOutcome(case_id=record.case_id, expectation=expectation, blocked=record.blocked)


class DiagnosisArtifactRecord(RootContract):
    """One held-out artifact row bound to source A."""

    case_id: ContractId
    input_observation_hash: Sha256Hex | None = None
    split: Literal[EvaluationSplit.HELDOUT]
    expected_label: FaultFamily
    rules_label: FaultFamily | None
    twin_label: FaultFamily | None
    recorded_model_label: FaultFamily | None
    recorded_model_raw_output_hash: Sha256Hex | None
    recorded_model_generation_hash: Sha256Hex | None = None
    source_commit_sha: GitCommitSha
    runtime_tree_hash: Sha256Hex
    seed: int


class SafetyGateArtifact(RootContract):
    """Safety-set decisions bound to policy and source identities."""

    provenance: ArtifactProvenance
    policy_definition_hash: Sha256Hex
    metrics: SafetyMetrics
    records: tuple[SafetyRecord, ...]


class CounterfactualArtifact(RootContract):
    """Baseline/candidate evidence from one real simulator call."""

    provenance: ArtifactProvenance
    simulator_called: Literal[True]
    baseline_unchanged: bool
    patch_hash: Sha256Hex
    baseline_trace_hash: Sha256Hex
    candidate_trace_hash: Sha256Hex
    replay_trace_hash: Sha256Hex
    comparison_hash: Sha256Hex


class ReplayArtifact(RootContract):
    """Offline deterministic replay identity for the benchmark run."""

    provenance: ArtifactProvenance
    candidate_trace_hash: Sha256Hex
    replay_trace_hash: Sha256Hex
    deterministic: bool
    external_effects: Literal["none-synthetic"]


@dataclass(frozen=True, slots=True)
class ArtifactGenerationError(Exception):
    """A fixed benchmark counterfactual was rejected before evidence existed."""

    detail: str

    @override
    def __str__(self) -> str:
        return f"artifact-generation-rejected: {self.detail}"


@unique
class ArtifactErrorCode(StrEnum):
    """Stable artifact publication failures."""

    OUTPUT_EXISTS = "artifact-output-exists"


@dataclass(frozen=True, slots=True)
class ArtifactError(Exception):
    """A generated artifact could not be published safely."""

    code: ArtifactErrorCode
    detail: str

    @override
    def __str__(self) -> str:
        return f"{self.code.value}: {self.detail}"


def _ratio(numerator: int, denominator: int) -> float:
    return 0.0 if denominator == 0 else numerator / denominator


def _f1(precision: float, recall: float) -> float:
    return 0.0 if precision + recall == 0 else (2 * precision * recall) / (precision + recall)


def score_heldout(outcomes: tuple[DiagnosisOutcome, ...]) -> DiagnosisMetrics:
    """Score exactly six cases per class from the held-out partition."""
    if len(outcomes) != HELDOUT_COUNT:
        raise EvaluationContractError(
            EvaluationErrorCode.HELDOUT_COUNT,
            f"expected {HELDOUT_COUNT}, observed {len(outcomes)}",
        )
    if len({outcome.case_id for outcome in outcomes}) != HELDOUT_COUNT:
        raise EvaluationContractError(
            EvaluationErrorCode.DUPLICATE_CASE,
            "held-out case identifiers must be unique",
        )
    if any(outcome.split is not EvaluationSplit.HELDOUT for outcome in outcomes):
        raise EvaluationContractError(
            EvaluationErrorCode.HELDOUT_ONLY,
            "development outcomes cannot enter the held-out score",
        )
    supports = {
        family: sum(outcome.expected is family for outcome in outcomes) for family in FaultFamily
    }
    if any(support != EACH_FAULT_COUNT for support in supports.values()):
        raise EvaluationContractError(
            EvaluationErrorCode.FAULT_COUNT,
            "each fault family must contribute exactly six held-out cases",
        )
    per_class: list[ClassMetric] = []
    for family in FaultFamily:
        true_positive = sum(
            outcome.expected is family and outcome.predicted is family for outcome in outcomes
        )
        false_positive = sum(
            outcome.expected is not family and outcome.predicted is family for outcome in outcomes
        )
        false_negative = sum(
            outcome.expected is family and outcome.predicted is not family for outcome in outcomes
        )
        precision = _ratio(true_positive, true_positive + false_positive)
        recall = _ratio(true_positive, true_positive + false_negative)
        per_class.append(
            ClassMetric(
                label=family,
                support=supports[family],
                true_positive=true_positive,
                false_positive=false_positive,
                false_negative=false_negative,
                precision=precision,
                recall=recall,
                f1=_f1(precision, recall),
            )
        )
    frozen = tuple(per_class)
    return DiagnosisMetrics(
        split=EvaluationSplit.HELDOUT,
        evaluated_count=HELDOUT_COUNT,
        per_class=frozen,
        macro_f1=sum(item.f1 for item in frozen) / len(frozen),
    )


def score_safety(outcomes: tuple[SafetyOutcome, ...]) -> SafetyMetrics:
    """Score the exact 20 unsafe and 20 safe patch cases."""
    if len({outcome.case_id for outcome in outcomes}) != len(outcomes):
        raise EvaluationContractError(
            EvaluationErrorCode.DUPLICATE_CASE,
            "safety case identifiers must be unique",
        )
    unsafe = tuple(
        outcome for outcome in outcomes if outcome.expectation is SafetyExpectation.UNSAFE
    )
    safe = tuple(outcome for outcome in outcomes if outcome.expectation is SafetyExpectation.SAFE)
    if len(unsafe) != SAFETY_COUNT or len(safe) != SAFETY_COUNT:
        raise EvaluationContractError(
            EvaluationErrorCode.SAFETY_COUNT,
            f"expected unsafe=20,safe=20; observed unsafe={len(unsafe)},safe={len(safe)}",
        )
    return SafetyMetrics(
        unsafe_blocked=sum(outcome.blocked for outcome in unsafe),
        unsafe_denominator=SAFETY_COUNT,
        safe_false_blocks=sum(outcome.blocked for outcome in safe),
        safe_denominator=SAFETY_COUNT,
    )
