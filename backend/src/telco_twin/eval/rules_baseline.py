"""Typed diagnosis corpus and deterministic rules baseline."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum, unique
from typing import TYPE_CHECKING, Annotated, Literal, Self, override

from pydantic import Field, ValidationError, model_validator

from telco_twin.domain._contract import (
    ContractId,
    RootContract,
    Sha256Hex,
    StrictContract,
    UtcTimestamp,
)
from telco_twin.domain._validation import fail_validation
from telco_twin.domain.canonical import canonical_model_bytes
from telco_twin.domain.scenario import FaultFamily
from telco_twin.eval.metrics import (
    EACH_FAULT_COUNT,
    HELDOUT_COUNT,
    SAFETY_COUNT,
    DiagnosisMetrics,
    EvaluationSplit,
    SafetyExpectation,
    SafetyMetrics,
    SafetyRecord,
)
from telco_twin.simulator.faults import DiagnosisStatus, diagnose_fault
from telco_twin.simulator.metrics import ObservationQualityFlag  # noqa: TC001
from telco_twin.simulator.network_model import NetworkObservation  # noqa: TC001

if TYPE_CHECKING:
    from pathlib import Path

CORPUS_COUNT = HELDOUT_COUNT * 2


@unique
class PredictionStatus(StrEnum):
    """Whether a baseline produced a class or abstained fail-closed."""

    PREDICTED = "predicted"
    ABSTAINED = "abstained"


class DiagnosisCase(RootContract):
    """One frozen synthetic observation and its reference class."""

    case_id: ContractId
    split: EvaluationSplit
    fault_family: FaultFamily
    assessed_at: UtcTimestamp
    observation: NetworkObservation


class SplitMember(StrictContract):
    """Frozen split binding independent of JSONL ordering."""

    case_id: ContractId
    fault_family: FaultFamily
    observation_hash: Sha256Hex


class DiagnosisSplits(RootContract):
    """Immutable v1 development and held-out memberships."""

    development: Annotated[tuple[SplitMember, ...], Field(min_length=36, max_length=36)]
    heldout: Annotated[tuple[SplitMember, ...], Field(min_length=36, max_length=36)]
    development_usage: Literal["baseline-design-only"]
    heldout_usage: Literal["final-score-only"]

    @model_validator(mode="after")
    def membership_is_disjoint(self) -> Self:
        """Reject identifier or observation leakage across partitions."""
        development_ids = {member.case_id for member in self.development}
        heldout_ids = {member.case_id for member in self.heldout}
        development_hashes = {member.observation_hash for member in self.development}
        heldout_hashes = {member.observation_hash for member in self.heldout}
        if development_ids & heldout_ids or development_hashes & heldout_hashes:
            fail_validation("diagnosis_split_leakage", "diagnosis partitions overlap")
        return self


class DiagnosisPrediction(RootContract):
    """One rules or gated prediction with explicit quality abstention."""

    case_id: ContractId
    status: PredictionStatus
    label: FaultFamily | None
    quality_flags: tuple[ObservationQualityFlag, ...]


class DiagnosisDraft(RootContract):
    """Real baseline outputs before provenance/model attachment."""

    case_id: ContractId
    input_observation_hash: Sha256Hex
    split: EvaluationSplit
    expected_label: FaultFamily
    rules_label: FaultFamily | None
    twin_label: FaultFamily | None


@dataclass(frozen=True, slots=True)
class DiagnosisEvaluation:
    """Rules and gated results before provenance/model attachment."""

    records: tuple[DiagnosisDraft, ...]
    rules_metrics: DiagnosisMetrics
    twin_metrics: DiagnosisMetrics


@unique
class SafetyMode(StrEnum):
    """Closed adversarial modes represented by the safety fixture."""

    SAFE = "safe"
    PATCH_OUT_OF_RANGE = "patch-out-of-range"
    MISSING_SIMULATION = "missing-simulation"
    STALE_OBSERVATION = "stale-observation"
    BINDING_MISMATCH = "binding-mismatch"
    TAMPERED_COMPARISON = "tampered-comparison"


class SafetyCase(RootContract):
    """One deterministic patch-policy scenario."""

    case_id: ContractId
    expectation: SafetyExpectation
    mode: SafetyMode
    seed: int
    capacity_ues: int

    @model_validator(mode="after")
    def expectation_matches_mode(self) -> Self:
        """Bind safe only to the safe mode and every adversarial mode to unsafe."""
        safe_mode = self.mode is SafetyMode.SAFE
        safe_expectation = self.expectation is SafetyExpectation.SAFE
        if safe_mode != safe_expectation:
            fail_validation("safety_mode_expectation", "safety mode and expectation disagree")
        return self


@dataclass(frozen=True, slots=True)
class SafetyEvaluation:
    """Detailed safety records plus frozen denominator metrics."""

    records: tuple[SafetyRecord, ...]
    metrics: SafetyMetrics


@dataclass(frozen=True, slots=True)
class EvaluationDataError(Exception):
    """An untrusted evaluation fixture failed parsing or cross-binding."""

    path: Path
    detail: str

    @override
    def __str__(self) -> str:
        """Return one stable boundary error string."""
        return f"evaluation-data-invalid: {self.path}: {self.detail}"


@dataclass(frozen=True, slots=True)
class DiagnosisDataset:
    """Parsed and cross-bound diagnosis cases plus immutable split membership."""

    cases: tuple[DiagnosisCase, ...]
    splits: DiagnosisSplits


def observation_hash(case: DiagnosisCase) -> Sha256Hex:
    """Hash only the typed observation used by a baseline."""
    return hashlib.sha256(canonical_model_bytes(case.observation)).hexdigest()


def predict_rules(case: DiagnosisCase) -> DiagnosisPrediction:
    """Run the closed six-family production diagnosis rules."""
    diagnosis = diagnose_fault(case.observation)
    match diagnosis.status:  # noqa: MATCH_OK - exhaustive enum
        case DiagnosisStatus.PRIMARY:
            return DiagnosisPrediction(
                case_id=case.case_id,
                status=PredictionStatus.PREDICTED,
                label=diagnosis.primary_fault,
                quality_flags=(),
                schema_version="1.0",
            )
        case DiagnosisStatus.NO_FAULT | DiagnosisStatus.AMBIGUOUS:
            return DiagnosisPrediction(
                case_id=case.case_id,
                status=PredictionStatus.ABSTAINED,
                label=None,
                quality_flags=(),
                schema_version="1.0",
            )


def load_diagnosis_cases(path: Path) -> tuple[DiagnosisCase, ...]:
    """Parse nonempty JSONL records at the dataset boundary."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        if not lines or any(not line for line in lines):
            raise EvaluationDataError(path, "JSONL must contain nonempty lines")
        return tuple(DiagnosisCase.model_validate_json(line) for line in lines)
    except (OSError, ValidationError) as error:
        raise EvaluationDataError(path, "diagnosis JSONL failed validation") from error


def load_diagnosis_splits(path: Path) -> DiagnosisSplits:
    """Parse the frozen split manifest."""
    try:
        return DiagnosisSplits.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as error:
        raise EvaluationDataError(path, "split manifest failed validation") from error


def _validate_members(
    path: Path,
    cases: tuple[DiagnosisCase, ...],
    split: EvaluationSplit,
    members: tuple[SplitMember, ...],
) -> None:
    selected = tuple(case for case in cases if case.split is split)
    expected = tuple(
        SplitMember(
            case_id=case.case_id,
            fault_family=case.fault_family,
            observation_hash=observation_hash(case),
        )
        for case in selected
    )
    if expected != members:
        raise EvaluationDataError(path, f"{split.value} membership does not bind cases")
    if any(
        sum(member.fault_family is family for member in members) != EACH_FAULT_COUNT
        for family in FaultFamily
    ):
        raise EvaluationDataError(path, f"{split.value} per-fault counts changed")


def load_diagnosis_dataset(fixtures: Path) -> DiagnosisDataset:
    """Parse and cross-check exact 72-case membership without ID/hash leakage."""
    cases_path = fixtures / "cases-v1.jsonl"
    splits_path = fixtures / "splits-v1.json"
    cases = load_diagnosis_cases(cases_path)
    splits = load_diagnosis_splits(splits_path)
    if len(cases) != CORPUS_COUNT or len({case.case_id for case in cases}) != CORPUS_COUNT:
        raise EvaluationDataError(cases_path, "expected 72 unique diagnosis cases")
    hashes = tuple(observation_hash(case) for case in cases)
    if len(set(hashes)) != CORPUS_COUNT:
        raise EvaluationDataError(cases_path, "diagnosis observations are duplicated")
    _validate_members(splits_path, cases, EvaluationSplit.DEVELOPMENT, splits.development)
    _validate_members(splits_path, cases, EvaluationSplit.HELDOUT, splits.heldout)
    return DiagnosisDataset(cases=cases, splits=splits)


def load_safety_cases(path: Path) -> tuple[SafetyCase, ...]:
    """Parse and lock the exact 20 safe plus 20 unsafe safety records."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        cases = tuple(SafetyCase.model_validate_json(line) for line in lines if line)
    except (OSError, ValidationError) as error:
        raise EvaluationDataError(path, "safety JSONL failed validation") from error
    safe = tuple(case for case in cases if case.expectation is SafetyExpectation.SAFE)
    unsafe = tuple(case for case in cases if case.expectation is SafetyExpectation.UNSAFE)
    total = SAFETY_COUNT * 2
    if len(cases) != total or len(safe) != SAFETY_COUNT or len(unsafe) != SAFETY_COUNT:
        raise EvaluationDataError(path, "expected exactly 20 safe and 20 unsafe cases")
    if len({case.case_id for case in cases}) != total:
        raise EvaluationDataError(path, "safety identifiers must be unique")
    return cases
