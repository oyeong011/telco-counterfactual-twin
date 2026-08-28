"""Independent replay verification for recorded-model comparison claims."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, override

from telco_twin.eval.metrics import (
    DiagnosisArtifactRecord,
    DiagnosisMetrics,
    DiagnosisOutcome,
    EvaluationSplit,
    score_heldout,
)
from telco_twin.eval.model_evidence import (
    ModelEvidenceContext,
    RecordedModelGeneration,
    RecordedModelPrediction,
    build_model_prediction,
)

if TYPE_CHECKING:
    from telco_twin.eval.model_replay_contracts import ModelReplayResult

type ModelEvidenceStatus = Literal["not_run", "ready", "completed"]


@dataclass(frozen=True, slots=True)
class ModelEvidenceInput:
    """Parsed artifact state needed for independent completed-model verification."""

    status: ModelEvidenceStatus
    comparison_allowed: bool
    predictions: tuple[RecordedModelPrediction, ...]
    generation: RecordedModelGeneration | None
    records: tuple[DiagnosisArtifactRecord, ...]
    claimed_metrics: DiagnosisMetrics | None
    context: ModelEvidenceContext
    replay: ModelReplayResult | None


@dataclass(frozen=True, slots=True)
class ModelEvidenceError(Exception):
    """A model comparison is missing or contradicts independently bound evidence."""

    detail: str

    @override
    def __str__(self) -> str:
        return f"completed-model-evidence-invalid: {self.detail}"


def _require(condition: bool, detail: str) -> None:
    if not condition:
        raise ModelEvidenceError(detail)


def _verify_not_run(evidence: ModelEvidenceInput) -> None:
    _require(evidence.replay is None, "not-run replay evidence present")
    _require(not evidence.comparison_allowed, "not-run comparison enabled")
    _require(not evidence.predictions, "not-run predictions present")
    _require(evidence.generation is None, "not-run generation receipt present")
    _require(evidence.claimed_metrics is None, "not-run metrics present")
    _require(
        all(
            record.recorded_model_label is None
            and record.recorded_model_raw_output_hash is None
            and record.recorded_model_generation_hash is None
            for record in evidence.records
        ),
        "not-run per-case evidence present",
    )


def _verify_completed(evidence: ModelEvidenceInput) -> None:
    generation = evidence.generation
    metrics = evidence.claimed_metrics
    replay = evidence.replay
    _require(replay is not None, "replayed model outputs missing")
    _require(evidence.comparison_allowed, "completed comparison disabled")
    _require(generation is not None, "generation receipt missing")
    _require(metrics is not None, "completed metrics missing")
    if generation is None or metrics is None or replay is None:
        return
    _require(len(evidence.predictions) == len(evidence.context.cases), "prediction count changed")
    _require(len(evidence.records) == len(evidence.context.cases), "artifact row count changed")
    _require(
        generation.model_manifest_hash == evidence.context.model_manifest_hash, "manifest drift"
    )
    _require(
        generation.model_snapshot_hash == replay.model_snapshot_hash,
        "model snapshot drift",
    )
    _require(generation.input_set_hash == evidence.context.input_set_hash, "input-set drift")
    _require(
        generation.prediction_hashes
        == tuple(prediction.prediction_hash for prediction in evidence.predictions),
        "prediction receipt drift",
    )
    _require(len(replay.prompts) == len(evidence.context.cases), "replayed prompt count changed")
    _require(
        len(replay.raw_outputs) == len(evidence.context.cases), "replayed output count changed"
    )
    outcomes: list[DiagnosisOutcome] = []
    for case, prediction, record, prompt, raw_output in zip(
        evidence.context.cases,
        evidence.predictions,
        evidence.records,
        replay.prompts,
        replay.raw_outputs,
        strict=True,
    ):
        _require(prediction.case_id == case.case_id == record.case_id, "case binding drift")
        _require(prediction.observation_hash == case.observation_hash, "observation drift")
        replayed_prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()
        _require(
            prediction.prompt_hash == case.prompt_hash == replayed_prompt_hash,
            "prompt drift",
        )
        _require(prediction.raw_output == raw_output, "raw output differs from replay")
        _require(
            prediction == build_model_prediction(case, raw_output),
            "prediction differs from replay",
        )
        _require(record.recorded_model_label is prediction.label, "record label drift")
        _require(
            record.recorded_model_raw_output_hash == prediction.raw_output_hash,
            "record raw-output hash drift",
        )
        _require(
            record.recorded_model_generation_hash == generation.generation_hash,
            "record generation hash drift",
        )
        outcomes.append(
            DiagnosisOutcome(
                case_id=case.case_id,
                split=EvaluationSplit.HELDOUT,
                expected=case.expected_label,
                predicted=prediction.label,
            )
        )
    _require(score_heldout(tuple(outcomes)) == metrics, "model metrics were not recomputed")


def verify_model_evidence(evidence: ModelEvidenceInput) -> None:
    """Verify not-run honestly or recompute every completed-model claim."""
    match evidence.status:  # noqa: MATCH_OK - exhaustive literal
        case "not_run":
            _verify_not_run(evidence)
        case "ready":
            detail = "ready model was not executed"
            raise ModelEvidenceError(detail)
        case "completed":
            _verify_completed(evidence)
