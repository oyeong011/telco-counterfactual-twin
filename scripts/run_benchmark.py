#!/usr/bin/env -S uv run --project backend python
# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = []
# ///

# ─── How to run ───
# 1. Install uv (if not installed):
#      curl -LsSf https://astral.sh/uv/install.sh | sh
# 2. Run through the pinned project:
#      uv run --project backend python scripts/run_benchmark.py --help
# 3. Or make executable and run:
#      chmod +x scripts/run_benchmark.py && ./scripts/run_benchmark.py --help
# ──────────────────

"""Generate the complete held-out benchmark bundle from clean source A."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Final, override

import typer
from pydantic import ValidationError
from telco_twin.eval.artifacts import (
    EvaluationDataError,
    build_benchmark_bundle,
    load_benchmark_inputs,
    write_bundle,
)
from telco_twin.eval.git_evidence import parse_name_status_z, parse_porcelain_status_z
from telco_twin.eval.metrics import (
    ArtifactError,
    EvaluationContractError,
    EvaluationErrorCode,
    EvaluationSplit,
)
from telco_twin.eval.model_replay import (
    QWEN_WORKER_CODE,
    ExactModelReplayVerifier,
)
from telco_twin.eval.model_replay_contracts import (
    ModelReplayUnavailableError,
    ModelWorkerRequest,
)
from telco_twin.eval.provenance import (
    DirtyWorktreeError,
    FreshnessError,
    ProvenanceRequest,
    RepositoryState,
    capture_provenance,
)
from telco_twin.eval.recorded_model_baseline import (
    ModelManifestError,
    RecordedModelManifest,
    RecordedModelResult,
    RecordedWorkerResponse,
    complete_recorded_model,
    not_run_recorded_model,
)
from telco_twin.eval.rules_baseline import DiagnosisCase

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = REPO_ROOT / "backend/fixtures/eval"
GIT_BINARY: Final = shutil.which("git") or "/usr/bin/git"


@dataclass(frozen=True, slots=True)
class GitProbeError(Exception):
    """A script-level Git fact could not be collected safely."""

    detail: str

    @override
    def __str__(self) -> str:
        return f"git-probe-failed: {self.detail}"


@dataclass(frozen=True, slots=True)
class SubprocessInferenceWorker:
    """Load pinned Qwen only inside one bounded, offline subprocess."""

    def infer(self, request: ModelWorkerRequest) -> tuple[str, ...]:
        """Run all exact prompts and parse only the typed worker response."""
        payload = {
            "cache": str(request.cache_directory),
            "prompts": request.prompts,
            "threads": request.threads,
            "max_output_units": request.max_output_units,
        }
        environment = os.environ.copy()
        environment.update(
            {
                "HF_HUB_OFFLINE": "1",
                "TRANSFORMERS_OFFLINE": "1",
                "TOKENIZERS_PARALLELISM": "false",
            }
        )
        try:
            completed = subprocess.run(
                (sys.executable, "-I", "-c", QWEN_WORKER_CODE),
                input=json.dumps(payload),
                capture_output=True,
                text=True,
                timeout=900,
                check=False,
                env=environment,
            )
        except subprocess.TimeoutExpired as error:
            detail = "model-worker-timeout"
            raise ModelReplayUnavailableError(detail) from error
        if completed.returncode != 0:
            detail = "model-worker-failed"
            raise ModelReplayUnavailableError(detail)
        try:
            response = RecordedWorkerResponse.model_validate_json(completed.stdout)
        except ValidationError as error:
            detail = "model-worker-evidence-invalid"
            raise ModelReplayUnavailableError(detail) from error
        return response.labels


def _git(repo_root: Path, arguments: tuple[str, ...]) -> str:
    try:
        completed = subprocess.run(
            (GIT_BINARY, "-C", str(repo_root), *arguments),
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        raise GitProbeError("Git command failed") from error
    return completed.stdout.rstrip("\n")


def repository_state(repo_root: Path, source_sha: str | None) -> RepositoryState:
    """Collect typed Git facts outside the scanner-governed product tree."""
    head_sha = _git(repo_root, ("rev-parse", "HEAD"))
    source = source_sha or head_sha
    committed = _git(repo_root, ("show", "-s", "--format=%cI", source))
    committed_at = (
        datetime.fromisoformat(committed).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    source_tree = _git(repo_root, ("rev-parse", f"{source}^{{tree}}"))
    status = _git(
        repo_root, ("status", "--porcelain=v1", "-z", "--untracked-files=all")
    )
    source_diff = _git(
        repo_root,
        ("diff", "--name-status", "-z", f"{source}..HEAD", "--"),
    )
    ancestry = subprocess.run(
        (
            GIT_BINARY,
            "-C",
            str(repo_root),
            "merge-base",
            "--is-ancestor",
            source,
            "HEAD",
        ),
        check=False,
        capture_output=True,
        timeout=30,
    )
    if ancestry.returncode not in {0, 1}:
        raise GitProbeError("Git ancestry probe failed")
    return RepositoryState(
        head_sha=head_sha,
        source_sha=source,
        source_tree_sha=source_tree,
        source_committed_at=committed_at,
        source_is_ancestor=ancestry.returncode == 0,
        status_entries=parse_porcelain_status_z(status),
        source_diff=parse_name_status_z(source_diff),
        schema_version="1.0",
    )


def _run_recorded_model(
    manifest: RecordedModelManifest,
    cases: tuple[DiagnosisCase, ...],
    cache_root: Path,
) -> RecordedModelResult:
    try:
        replay = ExactModelReplayVerifier(SubprocessInferenceWorker()).replay(
            manifest, cases, cache_root
        )
    except ModelReplayUnavailableError as error:
        return not_run_recorded_model(error.detail)
    return complete_recorded_model(manifest, cases, replay)


def main(
    split: Annotated[EvaluationSplit, typer.Option()],
    safety_set: Annotated[Path, typer.Option()],
    seed: Annotated[int, typer.Option()],
    out: Annotated[Path, typer.Option()],
    model_cache: Annotated[Path | None, typer.Option()] = None,
) -> None:
    """Run exact held-out rules, gated, safety, replay, and optional Qwen paths."""
    try:
        if split is not EvaluationSplit.HELDOUT:
            raise EvaluationContractError(
                code=EvaluationErrorCode.HELDOUT_ONLY,
                detail="benchmark artifacts are final-score heldout evidence",
            )
        provenance = capture_provenance(
            ProvenanceRequest(
                repo_root=REPO_ROOT,
                input_paths=(
                    FIXTURES / "cases-v1.jsonl",
                    FIXTURES / "splits-v1.json",
                    safety_set.resolve(),
                    FIXTURES / "model-manifest-v1.json",
                ),
                generator_invocation=("python", *sys.argv),
                output_path=out,
                seed=seed,
                split=split,
            ),
            repository_state(REPO_ROOT, None),
        )
        inputs = load_benchmark_inputs(FIXTURES, safety_set)
        cache_root = model_cache or REPO_ROOT / ".cache/recorded-model"
        heldout = tuple(
            case for case in inputs.cases if case.split is EvaluationSplit.HELDOUT
        )
        model = _run_recorded_model(inputs.model_manifest, heldout, cache_root)
        bundle = build_benchmark_bundle(inputs, provenance, model)
        write_bundle(bundle, out)
    except (
        ArtifactError,
        DirtyWorktreeError,
        EvaluationContractError,
        EvaluationDataError,
        FreshnessError,
        GitProbeError,
        ModelManifestError,
    ) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from error
    typer.echo(
        " ".join(
            (
                f"benchmark: PASS heldout={len(bundle.diagnosis_records)}",
                f"macro_f1={bundle.diagnosis_summary.twin_metrics.macro_f1:.6f}",
                f"model={bundle.diagnosis_summary.recorded_model.status.value}",
                f"out={out}",
            )
        )
    )


if __name__ == "__main__":
    typer.run(main)
