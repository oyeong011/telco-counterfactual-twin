"""Acceptance CLI and frozen fixture-recomputation integration tests."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from telco_twin.eval.acceptance import verify_bundle_claims
from telco_twin.eval.artifacts import (
    BenchmarkBundle,
    build_benchmark_bundle,
    load_benchmark_inputs,
    load_bundle,
    write_bundle,
)
from telco_twin.eval.model_evidence import RecordedModelPrediction
from telco_twin.eval.recorded_model_baseline import (
    ModelRunStatus,
    RecordedModelResult,
    inspect_recorded_model,
)

if TYPE_CHECKING:
    from telco_twin.eval.model_replay_contracts import ModelReplayResult, ReplayManifest
    from telco_twin.eval.rules_baseline import DiagnosisCase

REPO_ROOT = Path(__file__).parents[3]
FIXTURES = REPO_ROOT / "backend/fixtures/eval"


class ExplodingReplayVerifier:
    """Fail if truthful not-run acceptance attempts optional model loading."""

    def replay(
        self,
        manifest: ReplayManifest,
        cases: tuple[DiagnosisCase, ...],
        cache_root: Path,
    ) -> ModelReplayResult:
        raise AssertionError((manifest.revision, len(cases), cache_root))


def _fresh_not_run_bundle(cache_root: Path) -> BenchmarkBundle:
    inputs = load_benchmark_inputs(FIXTURES)
    provenance = load_bundle(REPO_ROOT / "artifacts/eval").diagnosis_summary.provenance
    model = inspect_recorded_model(inputs.model_manifest, cache_root)
    return build_benchmark_bundle(inputs, provenance, model)


def test_acceptance_cli_imports_when_invoked_by_path() -> None:
    # Given: the documented direct Python script invocation.
    # When: Typer loads the acceptance entry point from the repository root.
    result = subprocess.run(
        [sys.executable, "scripts/assert_acceptance.py", "--help"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    # Then: script-local imports resolve before argument handling.
    assert result.returncode == 0, result.stdout + result.stderr


def test_acceptance_rejects_fabricated_completed_model_bundle(tmp_path: Path) -> None:
    # Given: the truthful not-run bundle rewritten as an internally coherent completed claim.
    bundle = load_bundle(REPO_ROOT / "artifacts/eval")
    predictions = tuple(
        RecordedModelPrediction.model_construct(
            case_id=record.case_id,
            label=record.expected_label,
            raw_output_hash="0" * 64,
            schema_version="1.0",
        )
        for record in bundle.diagnosis_records
    )
    forged_model = RecordedModelResult.model_construct(
        status=ModelRunStatus.COMPLETED,
        reason="completed",
        comparison_allowed=True,
        predictions=predictions,
        schema_version="1.0",
    )
    forged = BenchmarkBundle(
        diagnosis_records=tuple(
            record.model_copy(
                update={
                    "recorded_model_label": record.expected_label,
                    "recorded_model_raw_output_hash": "0" * 64,
                }
            )
            for record in bundle.diagnosis_records
        ),
        diagnosis_summary=bundle.diagnosis_summary.model_copy(
            update={
                "recorded_model": forged_model,
                "recorded_model_metrics": bundle.diagnosis_summary.rules_metrics,
            }
        ),
        counterfactual=bundle.counterfactual,
        safety_gate=bundle.safety_gate,
        replay=bundle.replay,
    )
    forged_dir = tmp_path / "forged-completed"
    write_bundle(forged, forged_dir)
    # When: the real acceptance CLI validates the forged completed comparison.
    result = subprocess.run(
        [sys.executable, "scripts/assert_acceptance.py", str(forged_dir)],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    # Then: artifact evidence fails before dirty-source provenance can mask the exploit.
    output = result.stdout + result.stderr
    assert result.returncode == 2, output
    assert "dirty-worktree" not in output


def test_acceptance_recomputes_rows_from_frozen_fixtures(tmp_path: Path) -> None:
    # Given: zero diagnosis predictions and all safe rows blocked, but summaries left perfect.
    bundle = _fresh_not_run_bundle(tmp_path / "empty-cache")
    diagnosis_records = tuple(
        record.model_copy(update={"rules_label": None, "twin_label": None})
        for record in bundle.diagnosis_records
    )
    safety_records = tuple(
        record.model_copy(update={"blocked": True}) if not record.expected_unsafe else record
        for record in bundle.safety_gate.records
    )
    forged = BenchmarkBundle(
        diagnosis_records=diagnosis_records,
        diagnosis_summary=bundle.diagnosis_summary,
        counterfactual=bundle.counterfactual,
        safety_gate=bundle.safety_gate.model_copy(update={"records": safety_records}),
        replay=bundle.replay,
    )
    forged_dir = tmp_path / "contradictory-rows"
    write_bundle(forged, forged_dir)
    # When: the real acceptance CLI validates the contradictory artifact rows.
    result = subprocess.run(
        [sys.executable, "scripts/assert_acceptance.py", str(forged_dir)],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    # Then: replay rejects before dirty provenance can mask the defect.
    output = result.stdout + result.stderr
    assert result.returncode == 2, output
    assert "dirty-worktree" not in output


def test_acceptance_recomputes_canonical_counterfactual(tmp_path: Path) -> None:
    # Given: internally coherent but arbitrary counterfactual and replay identities.
    bundle = _fresh_not_run_bundle(tmp_path / "empty-cache")
    forged_counterfactual = bundle.counterfactual.model_copy(
        update={
            "patch_hash": "a" * 64,
            "baseline_trace_hash": "b" * 64,
            "candidate_trace_hash": "c" * 64,
            "replay_trace_hash": "c" * 64,
            "comparison_hash": "d" * 64,
        }
    )
    forged_replay = bundle.replay.model_copy(
        update={
            "candidate_trace_hash": "c" * 64,
            "replay_trace_hash": "c" * 64,
            "deterministic": True,
        }
    )
    forged = BenchmarkBundle(
        diagnosis_records=bundle.diagnosis_records,
        diagnosis_summary=bundle.diagnosis_summary,
        counterfactual=forged_counterfactual,
        safety_gate=bundle.safety_gate,
        replay=forged_replay,
    )
    forged_dir = tmp_path / "coherent-counterfactual-forgery"
    write_bundle(forged, forged_dir)
    # When: the real acceptance CLI validates the self-consistent forged bundle.
    result = subprocess.run(
        [sys.executable, "scripts/assert_acceptance.py", str(forged_dir)],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    # Then: canonical recomputation rejects before dirty provenance can mask the defect.
    output = result.stdout + result.stderr
    assert result.returncode == 2, output
    assert "counterfactual differs from canonical replay" in output
    assert "dirty-worktree" not in output


def test_acceptance_requires_canonical_policy_definition(tmp_path: Path) -> None:
    # Given: canonical simulation artifacts paired with an arbitrary policy identity.
    bundle = _fresh_not_run_bundle(tmp_path / "empty-cache")
    forged = BenchmarkBundle(
        diagnosis_records=bundle.diagnosis_records,
        diagnosis_summary=bundle.diagnosis_summary,
        counterfactual=bundle.counterfactual,
        safety_gate=bundle.safety_gate.model_copy(update={"policy_definition_hash": "e" * 64}),
        replay=bundle.replay,
    )
    forged_dir = tmp_path / "policy-definition-forgery"
    write_bundle(forged, forged_dir)
    # When: the real acceptance CLI validates the forged policy identity.
    result = subprocess.run(
        [sys.executable, "scripts/assert_acceptance.py", str(forged_dir)],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    # Then: explicit production policy identity rejects before dirty provenance.
    output = result.stdout + result.stderr
    assert result.returncode == 2, output
    assert "local policy definition drift" in output
    assert "dirty-worktree" not in output


def test_truthful_not_run_acceptance_never_invokes_replay(tmp_path: Path) -> None:
    # Given: a fresh deterministic bundle built with an absent exact model cache.
    cache_root = tmp_path / "empty-cache"
    bundle = _fresh_not_run_bundle(cache_root)
    # When: non-Git acceptance validates the explicit not-run evidence.
    provenance = verify_bundle_claims(
        bundle,
        FIXTURES,
        cache_root,
        ExplodingReplayVerifier(),
    )
    # Then: acceptance succeeds without calling the exploding optional replayer.
    assert provenance == bundle.diagnosis_summary.provenance
    assert bundle.diagnosis_summary.recorded_model.comparison_allowed is False
