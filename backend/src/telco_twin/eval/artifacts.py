"""Evaluation fixture loading, real-adapter execution, and atomic artifacts."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import ValidationError

from telco_twin.domain.scenario import FaultFamily
from telco_twin.eval.git_evidence import EvaluationArtifactFile
from telco_twin.eval.metrics import (
    ArtifactError,
    ArtifactErrorCode,
    ArtifactProvenance,
    CounterfactualArtifact,
    DiagnosisArtifactRecord,
    DiagnosisOutcome,
    EvaluationSplit,
    ReplayArtifact,
    SafetyGateArtifact,
    score_heldout,
)
from telco_twin.eval.recorded_model_baseline import (
    DiagnosisSummary,
    ModelRunStatus,
    RecordedModelManifest,
    RecordedModelResult,
    load_model_manifest,
)
from telco_twin.eval.rules_baseline import (
    DiagnosisCase,
    DiagnosisDataset,
    DiagnosisDraft,
    DiagnosisEvaluation,
    DiagnosisSplits,
    EvaluationDataError,
    SafetyCase,
    load_diagnosis_cases,
    load_diagnosis_dataset,
    load_safety_cases,
    observation_hash,
    predict_rules,
)
from telco_twin.eval.twin_gated import (
    build_counterfactual_artifacts,
    evaluate_safety,
    predict_gated,
)
from telco_twin.safety.policy_models import LOCAL_POLICY_DEFINITION_HASH

if TYPE_CHECKING:
    from telco_twin.domain._contract import RootContract

__all__ = ("EvaluationDataError", "load_diagnosis_cases")


@dataclass(frozen=True, slots=True)
class BenchmarkInputs:
    """All parsed immutable v1 fixtures."""

    cases: tuple[DiagnosisCase, ...]
    splits: DiagnosisSplits
    safety_cases: tuple[SafetyCase, ...]
    model_manifest: RecordedModelManifest

    @property
    def fault_families(self) -> tuple[FaultFamily, ...]:
        return tuple(FaultFamily)


@dataclass(frozen=True, slots=True)
class BenchmarkBundle:
    """Complete in-memory representation of the five output files."""

    diagnosis_records: tuple[DiagnosisArtifactRecord, ...]
    diagnosis_summary: DiagnosisSummary
    counterfactual: CounterfactualArtifact
    safety_gate: SafetyGateArtifact
    replay: ReplayArtifact


def load_benchmark_inputs(
    fixtures: Path,
    safety_path: Path | None = None,
) -> BenchmarkInputs:
    """Parse every committed evaluation input and reject cross-corpus overlap."""
    diagnosis: DiagnosisDataset = load_diagnosis_dataset(fixtures)
    safety = load_safety_cases(safety_path or fixtures / "safety-v1.jsonl")
    if {case.case_id for case in diagnosis.cases} & {case.case_id for case in safety}:
        raise EvaluationDataError(fixtures, "diagnosis and safety identifiers overlap")
    return BenchmarkInputs(
        cases=diagnosis.cases,
        splits=diagnosis.splits,
        safety_cases=safety,
        model_manifest=load_model_manifest(fixtures / "model-manifest-v1.json"),
    )


def evaluate_diagnosis(
    inputs: BenchmarkInputs,
    split: EvaluationSplit,
) -> DiagnosisEvaluation:
    """Run both code baselines over one frozen split."""
    selected = tuple(case for case in inputs.cases if case.split is split)
    drafts: list[DiagnosisDraft] = []
    rules_outcomes: list[DiagnosisOutcome] = []
    twin_outcomes: list[DiagnosisOutcome] = []
    for case in selected:
        rules = predict_rules(case)
        twin = predict_gated(case)
        drafts.append(
            DiagnosisDraft(
                case_id=case.case_id,
                input_observation_hash=observation_hash(case),
                split=case.split,
                expected_label=case.fault_family,
                rules_label=rules.label,
                twin_label=twin.label,
                schema_version="1.0",
            )
        )
        rules_outcomes.append(
            DiagnosisOutcome(
                case_id=case.case_id,
                split=case.split,
                expected=case.fault_family,
                predicted=rules.label,
            )
        )
        twin_outcomes.append(
            DiagnosisOutcome(
                case_id=case.case_id,
                split=case.split,
                expected=case.fault_family,
                predicted=twin.label,
            )
        )
    return DiagnosisEvaluation(
        records=tuple(drafts),
        rules_metrics=score_heldout(tuple(rules_outcomes)),
        twin_metrics=score_heldout(tuple(twin_outcomes)),
    )


def build_benchmark_bundle(
    inputs: BenchmarkInputs,
    provenance: ArtifactProvenance,
    model: RecordedModelResult,
) -> BenchmarkBundle:
    """Build deterministic held-out, safety, counterfactual, and replay evidence."""
    diagnosis = evaluate_diagnosis(inputs, provenance.split)
    model_by_id = {prediction.case_id: prediction for prediction in model.predictions}
    generation_hash = model.generation.generation_hash if model.generation is not None else None
    records = tuple(
        DiagnosisArtifactRecord(
            case_id=draft.case_id,
            input_observation_hash=draft.input_observation_hash,
            split=EvaluationSplit.HELDOUT,
            expected_label=draft.expected_label,
            rules_label=draft.rules_label,
            twin_label=draft.twin_label,
            recorded_model_label=model_by_id[draft.case_id].label
            if draft.case_id in model_by_id
            else None,
            recorded_model_raw_output_hash=(
                model_by_id[draft.case_id].raw_output_hash if draft.case_id in model_by_id else None
            ),
            recorded_model_generation_hash=generation_hash,
            source_commit_sha=provenance.source_commit_sha,
            runtime_tree_hash=provenance.runtime_tree_hash,
            seed=provenance.seed,
            schema_version="1.0",
        )
        for draft in diagnosis.records
    )
    model_metrics = None
    if model.status is ModelRunStatus.COMPLETED:
        model_metrics = score_heldout(
            tuple(
                DiagnosisOutcome(
                    case_id=record.case_id,
                    split=record.split,
                    expected=record.expected_label,
                    predicted=record.recorded_model_label,
                )
                for record in records
            )
        )
    summary = DiagnosisSummary(
        provenance=provenance,
        rules_metrics=diagnosis.rules_metrics,
        twin_metrics=diagnosis.twin_metrics,
        recorded_model=model,
        recorded_model_metrics=model_metrics,
        development_cases_used=0,
        heldout_case_ids=tuple(record.case_id for record in records),
        schema_version="1.0",
    )
    safety = evaluate_safety(inputs.safety_cases)
    counterfactual, replay = build_counterfactual_artifacts(provenance)
    return BenchmarkBundle(
        diagnosis_records=records,
        diagnosis_summary=summary,
        counterfactual=counterfactual,
        safety_gate=SafetyGateArtifact(
            provenance=provenance,
            policy_definition_hash=LOCAL_POLICY_DEFINITION_HASH,
            metrics=safety.metrics,
            records=safety.records,
            schema_version="1.0",
        ),
        replay=replay,
    )


def _json(value: RootContract) -> str:
    return value.model_dump_json(indent=2) + "\n"


def write_bundle(bundle: BenchmarkBundle, output: Path) -> None:
    """Publish a complete bundle atomically, never preserving stale partial files."""
    if output.exists():
        raise ArtifactError(ArtifactErrorCode.OUTPUT_EXISTS, str(output))
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{output.name}.", dir=output.parent) as temporary:
        staging = Path(temporary)
        _ = (staging / EvaluationArtifactFile.DIAGNOSIS).write_text(
            "".join(record.model_dump_json() + "\n" for record in bundle.diagnosis_records),
            encoding="utf-8",
        )
        _ = (staging / EvaluationArtifactFile.DIAGNOSIS_SUMMARY).write_text(
            _json(bundle.diagnosis_summary), encoding="utf-8"
        )
        _ = (staging / EvaluationArtifactFile.COUNTERFACTUAL).write_text(
            _json(bundle.counterfactual), encoding="utf-8"
        )
        _ = (staging / EvaluationArtifactFile.SAFETY).write_text(
            _json(bundle.safety_gate), encoding="utf-8"
        )
        _ = (staging / EvaluationArtifactFile.REPLAY).write_text(
            _json(bundle.replay), encoding="utf-8"
        )
        _ = staging.replace(output)


def load_bundle(directory: Path) -> BenchmarkBundle:
    """Parse a generated bundle back through its closed artifact contracts."""
    try:
        records = tuple(
            DiagnosisArtifactRecord.model_validate_json(line)
            for line in (directory / EvaluationArtifactFile.DIAGNOSIS)
            .read_text(encoding="utf-8")
            .splitlines()
            if line
        )
        return BenchmarkBundle(
            diagnosis_records=records,
            diagnosis_summary=DiagnosisSummary.model_validate_json(
                (directory / EvaluationArtifactFile.DIAGNOSIS_SUMMARY).read_text(encoding="utf-8")
            ),
            counterfactual=CounterfactualArtifact.model_validate_json(
                (directory / EvaluationArtifactFile.COUNTERFACTUAL).read_text(encoding="utf-8")
            ),
            safety_gate=SafetyGateArtifact.model_validate_json(
                (directory / EvaluationArtifactFile.SAFETY).read_text(encoding="utf-8")
            ),
            replay=ReplayArtifact.model_validate_json(
                (directory / EvaluationArtifactFile.REPLAY).read_text(encoding="utf-8")
            ),
        )
    except (OSError, ValidationError) as error:
        raise EvaluationDataError(directory, "generated artifact bundle is invalid") from error
