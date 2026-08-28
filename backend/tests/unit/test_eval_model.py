"""Recorded-model manifest, input, snapshot, and replay-evidence tests."""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from telco_twin.eval.artifacts import (
    build_benchmark_bundle,
    load_benchmark_inputs,
    load_bundle,
    write_bundle,
)
from telco_twin.eval.metrics import EvaluationSplit
from telco_twin.eval.model_evidence import (
    RecordedModelGeneration,
    RecordedModelPrediction,
)
from telco_twin.eval.model_input import fault_code, recorded_model_prompts
from telco_twin.eval.model_replay import ExactModelReplayVerifier, verify_model_snapshot
from telco_twin.eval.model_replay_contracts import (
    ModelReplayResult,
    ModelReplayUnavailableError,
    ModelSnapshotError,
    ModelWorkerRequest,
    ReplayManifest,
)
from telco_twin.eval.model_verification import (
    ModelEvidenceError,
    ModelEvidenceInput,
    verify_model_evidence,
)
from telco_twin.eval.recorded_model_baseline import (
    ModelFilePin,
    ModelRunStatus,
    RecordedModelResult,
    complete_recorded_model,
    expected_model_context,
    inspect_recorded_model,
    load_model_manifest,
)
from telco_twin.eval.rules_baseline import DiagnosisCase, predict_rules

FIXTURES = Path(__file__).parents[2] / "fixtures/eval"
REPO_ROOT = Path(__file__).parents[3]


class DeterministicFakeReplayVerifier:
    """Derive deterministic test outputs from the production rules adapter."""

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


class ExplodingInferenceWorker:
    """Fail if unavailable-cache handling attempts to load model code."""

    def infer(self, request: ModelWorkerRequest) -> tuple[str, ...]:
        raise AssertionError(request.cache_directory)


def _completed_model() -> RecordedModelResult:
    inputs = load_benchmark_inputs(FIXTURES)
    heldout = tuple(case for case in inputs.cases if case.split is EvaluationSplit.HELDOUT)
    replay = DeterministicFakeReplayVerifier().replay(
        inputs.model_manifest,
        heldout,
        FIXTURES,
    )
    return complete_recorded_model(inputs.model_manifest, heldout, replay)


def test_recorded_model_manifest_is_exact_and_missing_cache_is_not_run() -> None:
    # Given: the committed exact Qwen manifest and an empty cache.
    manifest_path = Path(__file__).parents[2] / "fixtures/eval/model-manifest-v1.json"
    manifest = load_model_manifest(manifest_path)
    # When: availability is inspected without any acquisition request.
    result = inspect_recorded_model(manifest, manifest_path.parent / "missing-cache")
    # Then: all pins are exact and the comparison is explicitly not run.
    assert manifest.model_id == "Qwen/Qwen2.5-1.5B-Instruct"
    assert manifest.revision == "989aa7980e4cf806f80c7fef2b1adb7bc71aa306"
    assert manifest.weight_sha256 == (
        "dd924a11b4c220f385b51ffa522daea7c9f3d850e31b162bb5661df483c6d3ee"
    )
    assert manifest.runtime.python == "3.12"
    assert manifest.runtime.transformers == "5.16.1"
    assert manifest.runtime.torch == "2.13.0"
    assert manifest.runtime.huggingface_hub == "1.28.0"
    assert result.status is ModelRunStatus.NOT_RUN
    assert result.comparison_allowed is False


def test_recorded_model_manifest_pins_every_loader_consumed_file() -> None:
    # Given/When: the exact optional Qwen manifest is parsed.
    manifest = load_model_manifest(FIXTURES / "model-manifest-v1.json")
    # Then: model, config, generation, and complete tokenizer inputs are all pinned.
    assert tuple(pin.path for pin in manifest.snapshot_files) == (
        "config.json",
        "generation_config.json",
        "merges.txt",
        "model.safetensors",
        "tokenizer.json",
        "tokenizer_config.json",
        "vocab.json",
    )


def test_snapshot_verifier_rejects_tampered_auxiliary_file(tmp_path: Path) -> None:
    # Given: a content-addressed auxiliary config that initially matches its pin.
    config = tmp_path / "config.json"
    original = b'{"model_type":"qwen2"}\n'
    _ = config.write_bytes(original)
    pin = ModelFilePin(path=config.name, sha256=hashlib.sha256(original).hexdigest())
    _ = verify_model_snapshot(tmp_path, (pin,))
    # When: auxiliary bytes change while the model identity claim stays fixed.
    _ = config.write_bytes(b'{"model_type":"altered"}\n')
    # Then: complete-snapshot verification rejects before inference.
    with pytest.raises(ModelSnapshotError, match=r"file hash mismatch: config\.json"):
        _ = verify_model_snapshot(tmp_path, (pin,))


def test_missing_snapshot_never_loads_the_inference_worker(tmp_path: Path) -> None:
    # Given: exact manifest/cases, an absent cache root, and a worker that must not run.
    inputs = load_benchmark_inputs(FIXTURES)
    heldout = tuple(case for case in inputs.cases if case.split is EvaluationSplit.HELDOUT)
    verifier = ExactModelReplayVerifier(ExplodingInferenceWorker())
    # When/Then: unavailable snapshot fails before optional runtime/model loading.
    with pytest.raises(ModelReplayUnavailableError, match="snapshot-unavailable"):
        _ = verifier.replay(inputs.model_manifest, heldout, tmp_path)


def test_recorded_model_prediction_rejects_arbitrary_raw_hash() -> None:
    # Given: a valid content-bound completed prediction with its raw output retained.
    prediction = _completed_model().predictions[0]
    tampered = prediction.model_dump_json().replace(prediction.raw_output_hash, "0" * 64, 1)
    # When/Then: parsing independently recomputes raw bytes and rejects the arbitrary hash.
    with pytest.raises(ValidationError):
        _ = RecordedModelPrediction.model_validate_json(tampered)


def test_recorded_model_generation_rejects_duplicate_prediction_hash() -> None:
    # Given: a valid generation receipt with distinct case-bound prediction hashes.
    generation = _completed_model().generation
    assert generation is not None
    tampered = generation.model_dump_json().replace(
        generation.prediction_hashes[1],
        generation.prediction_hashes[0],
        1,
    )
    # When/Then: parsing rejects a duplicated prediction identity.
    with pytest.raises(ValidationError):
        _ = RecordedModelGeneration.model_validate_json(tampered)


def test_cache_ready_boolean_cannot_certify_completed_model() -> None:
    # Given: content-coherent outputs and no independently replayed evidence.
    inputs = load_benchmark_inputs(FIXTURES)
    heldout = tuple(case for case in inputs.cases if case.split is EvaluationSplit.HELDOUT)
    model = _completed_model()
    provenance = load_bundle(REPO_ROOT / "artifacts/eval").diagnosis_summary.provenance
    bundle = build_benchmark_bundle(inputs, provenance, model)
    # When/Then: readiness alone cannot substitute for rerunning exact inference.
    with pytest.raises(ModelEvidenceError, match="replayed model outputs missing"):
        verify_model_evidence(
            ModelEvidenceInput(
                status=model.status.value,
                comparison_allowed=model.comparison_allowed,
                predictions=model.predictions,
                generation=model.generation,
                records=bundle.diagnosis_records,
                claimed_metrics=bundle.diagnosis_summary.recorded_model_metrics,
                context=expected_model_context(inputs.model_manifest, heldout),
                replay=None,
            )
        )


def test_acceptance_rejects_content_coherent_fabrication_without_exact_cache(
    tmp_path: Path,
) -> None:
    # Given: fully hash-bound raw outputs fabricated from references without a model cache.
    inputs = load_benchmark_inputs(FIXTURES)
    heldout = tuple(case for case in inputs.cases if case.split is EvaluationSplit.HELDOUT)
    model = complete_recorded_model(
        inputs.model_manifest,
        heldout,
        ModelReplayResult(
            prompts=recorded_model_prompts(heldout),
            raw_outputs=tuple(fault_code(case.fault_family) for case in heldout),
            model_snapshot_hash="b" * 64,
        ),
    )
    provenance = load_bundle(REPO_ROOT / "artifacts/eval").diagnosis_summary.provenance
    forged_dir = tmp_path / "coherent-fabrication"
    write_bundle(build_benchmark_bundle(inputs, provenance, model), forged_dir)
    # When: the real CLI verifies completed evidence against an explicitly empty cache root.
    result = subprocess.run(
        [
            sys.executable,
            "scripts/assert_acceptance.py",
            str(forged_dir),
            "--model-cache",
            str(tmp_path / "empty-cache"),
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    # Then: coherent artifact-only fabrication fails before provenance can mask it.
    output = result.stdout + result.stderr
    assert result.returncode == 2, output
    assert "exact model cache/runtime unavailable" in output
    assert "dirty-worktree" not in output
