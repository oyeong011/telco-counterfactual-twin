"""Optional exact-cache Qwen diagnosis baseline with offline-only inference."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum, unique
from typing import TYPE_CHECKING, Annotated, Final, Literal, Self, override

from pydantic import Field, ValidationError, model_validator

from telco_twin.domain._contract import (
    ContractId,
    GitCommitSha,
    RootContract,
    Sha256Hex,
    StrictContract,
)
from telco_twin.domain._validation import fail_validation
from telco_twin.domain.canonical import canonical_model_bytes
from telco_twin.eval.metrics import (
    HELDOUT_COUNT,
    ArtifactProvenance,
    DiagnosisMetrics,
)
from telco_twin.eval.model_evidence import (
    ModelCaseBinding,
    ModelEvidenceContext,
    RecordedModelGeneration,
    RecordedModelPrediction,
    build_model_context,
    build_model_generation,
    build_model_prediction,
)
from telco_twin.eval.model_input import recorded_model_prompts
from telco_twin.eval.model_replay import inspect_model_availability
from telco_twin.eval.rules_baseline import DiagnosisCase, observation_hash

if TYPE_CHECKING:
    from pathlib import Path

    from telco_twin.eval.model_replay_contracts import ModelReplayResult

MODEL_ID: Final = "Qwen/Qwen2.5-1.5B-Instruct"
REVISION: Final = "989aa7980e4cf806f80c7fef2b1adb7bc71aa306"
WEIGHT_SHA256: Final = "dd924a11b4c220f385b51ffa522daea7c9f3d850e31b162bb5661df483c6d3ee"
THREAD_COUNT: Final = 4
MAX_OUTPUT_UNITS: Final = 128
MODEL_SNAPSHOT_FILES: Final = (
    ("config.json", "98d2ff8cc47488d08a2b0b3acf4eb99ef210779b42bd48605f6b8e36acdbf670"),
    (
        "generation_config.json",
        "e558847a8b4402616f1273797b015104dc266fe4b520056fca88823ba8f8ebe6",
    ),
    ("merges.txt", "599bab54075088774b1733fde865d5bd747cbcc7a547c5bc12610e874e26f5e3"),
    ("model.safetensors", WEIGHT_SHA256),
    ("tokenizer.json", "c0382117ea329cdf097041132f6d735924b697924d6f6fc3945713e96ce87539"),
    (
        "tokenizer_config.json",
        "5b5d4f65d0acd3b2d56a35b56d374a36cbc1c8fa5cf3b3febbbfabf22f359583",
    ),
    ("vocab.json", "ca10d7e9fb3ed18575dd1e277a2579c16d108e32f27439684afa0e10b1440910"),
)


class ModelRuntime(RootContract):
    """Exact optional dependency and interpreter versions."""

    python: str
    transformers: str
    torch: str
    huggingface_hub: str


class InferenceProtocol(RootContract):
    """Frozen CPU-only generation settings."""

    device: str
    dtype: str
    threads: Annotated[int, Field(strict=True)]
    batch_size: Annotated[int, Field(strict=True)]
    decoding: str
    max_output_units: Annotated[int, Field(strict=True)]


class ModelFilePin(StrictContract):
    """One exact loader-consumed file in the recorded-model snapshot."""

    path: str
    sha256: Sha256Hex


class RecordedModelManifest(RootContract):
    """Acquisition and inference identity for the optional baseline."""

    model_id: str
    revision: GitCommitSha
    weight_file: str
    weight_sha256: Sha256Hex
    snapshot_files: Annotated[tuple[ModelFilePin, ...], Field(min_length=7, max_length=7)]
    runtime: ModelRuntime
    inference: InferenceProtocol

    @model_validator(mode="after")
    def pins_are_exact(self) -> Self:
        """Reject any manifest that weakens or changes the recorded protocol."""
        expected = (
            self.model_id == MODEL_ID
            and self.revision == REVISION
            and self.weight_file == "model.safetensors"
            and self.weight_sha256 == WEIGHT_SHA256
            and tuple((item.path, item.sha256) for item in self.snapshot_files)
            == MODEL_SNAPSHOT_FILES
            and self.runtime.python == "3.12"
            and self.runtime.transformers == "5.16.1"
            and self.runtime.torch == "2.13.0"
            and self.runtime.huggingface_hub == "1.28.0"
            and self.inference.device == "cpu"
            and self.inference.dtype == "float32"
            and self.inference.threads == THREAD_COUNT
            and self.inference.batch_size == 1
            and self.inference.decoding == "greedy"
            and self.inference.max_output_units == MAX_OUTPUT_UNITS
        )
        if not expected:
            fail_validation("recorded_model_pins", "recorded model manifest pins changed")
        return self


@unique
class ModelRunStatus(StrEnum):
    """Truthful optional baseline state."""

    NOT_RUN = "not_run"
    READY = "ready"
    COMPLETED = "completed"


class RecordedModelResult(RootContract):
    """Optional model result; not-run has no predictions or comparison."""

    status: ModelRunStatus
    reason: str
    comparison_allowed: bool
    predictions: tuple[RecordedModelPrediction, ...]
    generation: RecordedModelGeneration | None = None

    @model_validator(mode="after")
    def evidence_matches_status(self) -> Self:
        """Make completed and unavailable model evidence distinct at parse time."""
        match self.status:  # noqa: MATCH_OK - exhaustive enum
            case ModelRunStatus.NOT_RUN | ModelRunStatus.READY:
                valid = (
                    not self.comparison_allowed and not self.predictions and self.generation is None
                )
            case ModelRunStatus.COMPLETED:
                valid = (
                    self.comparison_allowed
                    and len(self.predictions) == HELDOUT_COUNT
                    and self.generation is not None
                )
        if not valid:
            fail_validation("model_evidence_status", "model evidence contradicts run status")
        return self


class DiagnosisSummary(RootContract):
    """Aggregate diagnosis claims and optional-model status."""

    provenance: ArtifactProvenance
    rules_metrics: DiagnosisMetrics
    twin_metrics: DiagnosisMetrics
    recorded_model: RecordedModelResult
    recorded_model_metrics: DiagnosisMetrics | None
    development_cases_used: Literal[0]
    heldout_case_ids: tuple[ContractId, ...]


def not_run_recorded_model(reason: str) -> RecordedModelResult:
    """Return an explicit result that cannot support a model comparison."""
    return RecordedModelResult(
        status=ModelRunStatus.NOT_RUN,
        reason=reason,
        comparison_allowed=False,
        predictions=(),
        generation=None,
        schema_version="1.0",
    )


class RecordedWorkerResponse(RootContract):
    """Untrusted offline worker output parsed by the benchmark script."""

    labels: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ModelManifestError(Exception):
    """The model manifest could not be parsed at its file boundary."""

    path: Path

    @override
    def __str__(self) -> str:
        return f"invalid-recorded-model-manifest: {self.path}"


def load_model_manifest(path: Path) -> RecordedModelManifest:
    """Parse the exact committed model manifest."""
    try:
        return RecordedModelManifest.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as error:
        raise ModelManifestError(path) from error


def inspect_recorded_model(
    manifest: RecordedModelManifest,
    cache_root: Path,
) -> RecordedModelResult:
    """Inspect only the exact local cache; never acquire packages or weights."""
    availability = inspect_model_availability(manifest, cache_root)
    return RecordedModelResult(
        status=ModelRunStatus.READY if availability.ready else ModelRunStatus.NOT_RUN,
        reason=availability.reason,
        comparison_allowed=False,
        predictions=(),
        generation=None,
        schema_version="1.0",
    )


def expected_model_context(
    manifest: RecordedModelManifest,
    cases: tuple[DiagnosisCase, ...],
) -> ModelEvidenceContext:
    """Bind exact manifest/runtime pins to ordered case, observation, and prompt hashes."""
    prompts = recorded_model_prompts(cases)
    bindings = tuple(
        ModelCaseBinding(
            case_id=case.case_id,
            expected_label=case.fault_family,
            observation_hash=observation_hash(case),
            prompt_hash=hashlib.sha256(prompt.encode()).hexdigest(),
        )
        for case, prompt in zip(cases, prompts, strict=True)
    )
    manifest_hash = hashlib.sha256(canonical_model_bytes(manifest)).hexdigest()
    return build_model_context(manifest_hash, bindings)


def complete_recorded_model(
    manifest: RecordedModelManifest,
    cases: tuple[DiagnosisCase, ...],
    replay: ModelReplayResult,
) -> RecordedModelResult:
    """Retain and bind outputs produced by one exact deterministic replay."""
    expected_prompts = recorded_model_prompts(cases)
    if replay.prompts != expected_prompts or len(replay.raw_outputs) != len(cases):
        return not_run_recorded_model("model-worker-count-mismatch")
    context = expected_model_context(manifest, cases)
    predictions = tuple(
        build_model_prediction(case, raw)
        for case, raw in zip(context.cases, replay.raw_outputs, strict=True)
    )
    return RecordedModelResult(
        status=ModelRunStatus.COMPLETED,
        reason="completed",
        comparison_allowed=True,
        predictions=predictions,
        generation=build_model_generation(
            context,
            predictions,
            replay.model_snapshot_hash,
        ),
        schema_version="1.0",
    )
