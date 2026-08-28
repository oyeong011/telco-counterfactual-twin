"""Completed-model deterministic replay verification integration test."""

from __future__ import annotations

from pathlib import Path

import pytest

from telco_twin.eval.artifacts import build_benchmark_bundle, load_benchmark_inputs, load_bundle
from telco_twin.eval.metrics import EvaluationSplit
from telco_twin.eval.model_input import fault_code, recorded_model_prompts
from telco_twin.eval.model_replay_contracts import ModelReplayResult, ReplayManifest
from telco_twin.eval.model_verification import (
    ModelEvidenceError,
    ModelEvidenceInput,
    verify_model_evidence,
)
from telco_twin.eval.recorded_model_baseline import (
    complete_recorded_model,
    expected_model_context,
)
from telco_twin.eval.rules_baseline import DiagnosisCase, predict_rules

REPO_ROOT = Path(__file__).parents[3]
FIXTURES = REPO_ROOT / "backend/fixtures/eval"


class DeterministicFakeReplayVerifier:
    """Generate test model outputs from real deterministic adapter behavior."""

    def replay(
        self,
        manifest: ReplayManifest,
        cases: tuple[DiagnosisCase, ...],
        cache_root: Path,
    ) -> ModelReplayResult:
        _ = manifest, cache_root
        labels = tuple(predict_rules(case).label for case in cases)
        assert all(label is not None for label in labels)
        return ModelReplayResult(
            prompts=recorded_model_prompts(cases),
            raw_outputs=tuple(fault_code(label) for label in labels if label is not None),
            model_snapshot_hash="a" * 64,
        )


def test_completed_model_evidence_recomputes_bound_metrics() -> None:
    # Given: raw outputs bound to the exact manifest, observations, prompts, and case order.
    inputs = load_benchmark_inputs(FIXTURES)
    heldout = tuple(case for case in inputs.cases if case.split is EvaluationSplit.HELDOUT)
    replay = DeterministicFakeReplayVerifier().replay(
        inputs.model_manifest,
        heldout,
        FIXTURES,
    )
    model = complete_recorded_model(inputs.model_manifest, heldout, replay)
    provenance = load_bundle(REPO_ROOT / "artifacts/eval").diagnosis_summary.provenance
    bundle = build_benchmark_bundle(inputs, provenance, model)
    evidence = ModelEvidenceInput(
        status=model.status.value,
        comparison_allowed=model.comparison_allowed,
        predictions=model.predictions,
        generation=model.generation,
        records=bundle.diagnosis_records,
        claimed_metrics=bundle.diagnosis_summary.recorded_model_metrics,
        context=expected_model_context(inputs.model_manifest, heldout),
        replay=replay,
    )
    # When: acceptance-grade verification independently recomputes every binding and metric.
    verify_model_evidence(evidence)
    # Then: raw content is retained and copied metrics cannot replace the recomputed result.
    assert model.generation is not None
    assert all(prediction.raw_output for prediction in model.predictions)
    wrong_metrics = bundle.diagnosis_summary.rules_metrics.model_copy(update={"macro_f1": 0.0})
    with pytest.raises(ModelEvidenceError, match="metrics were not recomputed"):
        verify_model_evidence(
            ModelEvidenceInput(
                status=evidence.status,
                comparison_allowed=evidence.comparison_allowed,
                predictions=evidence.predictions,
                generation=evidence.generation,
                records=evidence.records,
                claimed_metrics=wrong_metrics,
                context=evidence.context,
                replay=evidence.replay,
            )
        )
    replay_drifts = (
        (
            ModelReplayResult(
                prompts=(replay.prompts[0] + " altered", *replay.prompts[1:]),
                raw_outputs=replay.raw_outputs,
                model_snapshot_hash=replay.model_snapshot_hash,
            ),
            "prompt drift",
        ),
        (
            ModelReplayResult(
                prompts=replay.prompts,
                raw_outputs=("C1", *replay.raw_outputs[1:]),
                model_snapshot_hash=replay.model_snapshot_hash,
            ),
            "raw output differs from replay",
        ),
        (
            ModelReplayResult(
                prompts=replay.prompts,
                raw_outputs=replay.raw_outputs,
                model_snapshot_hash="b" * 64,
            ),
            "model snapshot drift",
        ),
    )
    for drifted_replay, expected_error in replay_drifts:
        with pytest.raises(ModelEvidenceError, match=expected_error):
            verify_model_evidence(
                ModelEvidenceInput(
                    status=evidence.status,
                    comparison_allowed=evidence.comparison_allowed,
                    predictions=evidence.predictions,
                    generation=evidence.generation,
                    records=evidence.records,
                    claimed_metrics=evidence.claimed_metrics,
                    context=evidence.context,
                    replay=drifted_replay,
                )
            )
