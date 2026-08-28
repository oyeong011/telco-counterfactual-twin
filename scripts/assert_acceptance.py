#!/usr/bin/env -S uv run --project backend python
# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = []
# ///

# ─── How to run ───
# 1. Install uv (if not installed):
#      curl -LsSf https://astral.sh/uv/install.sh | sh
# 2. Run through the pinned project:
#      uv run --project backend python scripts/assert_acceptance.py artifacts/eval
# 3. Or make executable and run:
#      chmod +x scripts/assert_acceptance.py && ./scripts/assert_acceptance.py artifacts/eval
# ──────────────────

"""Assert immutable Task-6 thresholds, provenance, replay, and honest not-run."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Final

import typer
from pydantic import ValidationError
from telco_twin.eval.acceptance import AcceptanceError, verify_bundle_claims
from telco_twin.eval.artifacts import (
    EvaluationDataError,
    load_bundle,
)
from telco_twin.eval.git_evidence import (
    CANONICAL_EVAL_FILENAMES,
    parse_name_status_z,
    parse_porcelain_status_z,
)
from telco_twin.eval.model_replay import (
    QWEN_WORKER_CODE,
    ExactModelReplayVerifier,
)
from telco_twin.eval.model_replay_contracts import (
    ModelReplayUnavailableError,
    ModelWorkerRequest,
)
from telco_twin.eval.model_verification import ModelEvidenceError
from telco_twin.eval.provenance import (
    DirtyWorktreeError,
    FreshnessError,
    RepositoryState,
    verify_provenance,
)
from telco_twin.eval.recorded_model_baseline import RecordedWorkerResponse

REPO_ROOT: Final = Path(__file__).resolve().parents[1]
FIXTURES: Final = REPO_ROOT / "backend/fixtures/eval"
GIT_BINARY: Final = shutil.which("git") or "/usr/bin/git"
EXPECTED_FILES: Final = frozenset(CANONICAL_EVAL_FILENAMES)


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


def _git(arguments: tuple[str, ...]) -> str:
    completed = subprocess.run(
        (GIT_BINARY, "-C", str(REPO_ROOT), *arguments),
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return completed.stdout.rstrip("\n")


def _repository_state(source_sha: str) -> RepositoryState:
    committed = _git(("show", "-s", "--format=%cI", source_sha))
    source_tree = _git(("rev-parse", f"{source_sha}^{{tree}}"))
    status = _git(("status", "--porcelain=v1", "-z", "--untracked-files=all"))
    source_diff = _git(("diff", "--name-status", "-z", f"{source_sha}..HEAD", "--"))
    ancestry = subprocess.run(
        (
            GIT_BINARY,
            "-C",
            str(REPO_ROOT),
            "merge-base",
            "--is-ancestor",
            source_sha,
            "HEAD",
        ),
        check=False,
        capture_output=True,
        timeout=30,
    )
    if ancestry.returncode not in {0, 1}:
        raise AcceptanceError("Git ancestry probe failed")
    committed_at = datetime.fromisoformat(committed).astimezone(UTC)
    return RepositoryState(
        head_sha=_git(("rev-parse", "HEAD")),
        source_sha=source_sha,
        source_tree_sha=source_tree,
        source_committed_at=committed_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        source_is_ancestor=ancestry.returncode == 0,
        status_entries=parse_porcelain_status_z(status),
        source_diff=parse_name_status_z(source_diff),
        schema_version="1.0",
    )


def main(
    artifact_dir: Path,
    model_cache: Annotated[Path | None, typer.Option()] = None,
) -> None:
    """Validate one freshly generated Task-6 artifact directory."""
    try:
        files = frozenset(
            path.name for path in artifact_dir.iterdir() if path.is_file()
        )
        if files != EXPECTED_FILES:
            raise AcceptanceError("artifact file set changed")
        bundle = load_bundle(artifact_dir)
        cache = model_cache or REPO_ROOT / ".cache/recorded-model"
        provenance = verify_bundle_claims(
            bundle,
            FIXTURES,
            cache,
            ExactModelReplayVerifier(SubprocessInferenceWorker()),
        )
        verify_provenance(
            REPO_ROOT,
            provenance,
            _repository_state(provenance.source_commit_sha),
        )
    except (
        AcceptanceError,
        DirtyWorktreeError,
        EvaluationDataError,
        FreshnessError,
        ModelEvidenceError,
        OSError,
        subprocess.SubprocessError,
    ) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from error
    typer.echo(
        " ".join(
            (
                "acceptance: PASS heldout=36",
                f"macro_f1={bundle.diagnosis_summary.twin_metrics.macro_f1:.6f}",
                "unsafe=20/20",
                f"safe_false_blocks={bundle.safety_gate.metrics.safe_false_blocks}/20",
                f"model={bundle.diagnosis_summary.recorded_model.status.value}",
            )
        )
    )


if __name__ == "__main__":
    typer.run(main)
