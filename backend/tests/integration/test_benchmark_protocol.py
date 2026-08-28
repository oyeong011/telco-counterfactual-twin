"""Real corpus, adapter, artifact, and provenance protocol tests."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from telco_twin.eval.artifacts import (
    EvaluationDataError,
    build_benchmark_bundle,
    evaluate_diagnosis,
    load_benchmark_inputs,
    load_diagnosis_cases,
    write_bundle,
)
from telco_twin.eval.git_evidence import parse_porcelain_status_z
from telco_twin.eval.metrics import ArtifactProvenance, EvaluationSplit, FileDigest
from telco_twin.eval.provenance import (
    DirtyWorktreeError,
    FreshnessError,
    require_clean_worktree,
    verify_provenance_identity,
)
from telco_twin.eval.recorded_model_baseline import inspect_recorded_model
from telco_twin.eval.twin_gated import evaluate_safety

REPO_ROOT = Path(__file__).parents[3]
FIXTURES = REPO_ROOT / "backend/fixtures/eval"


def test_frozen_corpus_has_exact_split_and_safety_counts() -> None:
    # Given: the committed diagnosis, split, and safety fixtures.
    # When: all untrusted JSON boundaries are parsed and cross-checked.
    inputs = load_benchmark_inputs(FIXTURES)
    # Then: the immutable v1 denominators and per-family counts are exact.
    assert len(inputs.cases) == 72
    assert len(inputs.splits.development) == 36
    assert len(inputs.splits.heldout) == 36
    assert len(inputs.safety_cases) == 40
    assert all(
        sum(member.fault_family is family for member in inputs.splits.development) == 6
        for family in inputs.fault_families
    )
    assert all(
        sum(member.fault_family is family for member in inputs.splits.heldout) == 6
        for family in inputs.fault_families
    )


def test_rules_and_gated_adapters_score_real_heldout_cases() -> None:
    # Given: all 36 held-out typed observations.
    inputs = load_benchmark_inputs(FIXTURES)
    # When: the rules baseline and quality-gated adapter traverse production diagnosis code.
    result = evaluate_diagnosis(inputs, EvaluationSplit.HELDOUT)
    # Then: both real adapters emit 36 predictions and clear the frozen threshold.
    assert len(result.records) == 36
    assert result.rules_metrics.macro_f1 >= 0.85
    assert result.twin_metrics.macro_f1 >= 0.85
    assert all(record.rules_label is not None for record in result.records)
    assert all(record.twin_label is not None for record in result.records)


def test_gated_adapter_blocks_real_unsafe_cases_without_false_success() -> None:
    # Given: the exact 20 unsafe and 20 safe patch cases.
    inputs = load_benchmark_inputs(FIXTURES)
    # When: each case traverses patch assessment, simulator, comparison, or local policy.
    result = evaluate_safety(inputs.safety_cases)
    # Then: unsafe20/20 and safe false-block<=2/20 use real simulator evidence.
    assert result.metrics.unsafe_blocked == 20
    assert result.metrics.safe_false_blocks <= 2
    assert sum(record.simulator_called for record in result.records) >= 20
    assert all(record.blocked for record in result.records if record.expected_unsafe)


def test_bundle_is_deterministic_and_model_not_run_has_no_comparison(tmp_path: Path) -> None:
    # Given: fixed inputs, provenance, seed, and an empty exact-model cache.
    inputs = load_benchmark_inputs(FIXTURES)
    provenance = ArtifactProvenance(
        source_commit_sha="1" * 40,
        source_committed_at="2026-08-28T00:00:00Z",
        runtime_tree_hash="2" * 64,
        inputs=(
            FileDigest(
                path="backend/fixtures/eval/cases-v1.jsonl",
                sha256="3" * 64,
                schema_version="1.0",
            ),
        ),
        generator_invocation=("python", "scripts/run_benchmark.py"),
        seed=20270827,
        split=EvaluationSplit.HELDOUT,
        schema_version="1.0",
    )
    model = inspect_recorded_model(inputs.model_manifest, tmp_path / "cache")
    first = build_benchmark_bundle(inputs, provenance, model)
    second = build_benchmark_bundle(inputs, provenance, model)
    # When: independent bundles are written.
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    write_bundle(first, first_dir)
    write_bundle(second, second_dir)
    # Then: bytes match and not-run never produces an LLM comparison claim.
    assert {path.name: path.read_bytes() for path in first_dir.iterdir()} == {
        path.name: path.read_bytes() for path in second_dir.iterdir()
    }
    assert first.diagnosis_summary.recorded_model.status.value == "not_run"
    assert first.diagnosis_summary.recorded_model_metrics is None
    assert all(record.recorded_model_label is None for record in first.diagnosis_records)


def test_dirty_worktree_is_rejected_before_generation(tmp_path: Path) -> None:
    # Given: a committed repository with a new untracked source file.
    _ = subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    _ = subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "Eval Test"], check=True)
    _ = subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "eval@example.invalid"],
        check=True,
    )
    tracked = tmp_path / "tracked.txt"
    _ = tracked.write_text("clean\n", encoding="utf-8")
    _ = subprocess.run(["git", "-C", str(tmp_path), "add", "tracked.txt"], check=True)
    _ = subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "fixture"], check=True)
    _ = (tmp_path / "rogue.txt").write_text("dirty\n", encoding="utf-8")
    status = subprocess.run(
        ["git", "-C", str(tmp_path), "status", "--porcelain=v1", "-z", "--untracked-files=all"],
        check=True,
        capture_output=True,
        text=True,
    )
    # When/Then: provenance capture refuses to generate evidence from dirty source.
    with pytest.raises(DirtyWorktreeError):
        require_clean_worktree(parse_porcelain_status_z(status.stdout))


def test_malformed_dataset_and_stale_provenance_fail_closed(tmp_path: Path) -> None:
    # Given: malformed JSONL plus an artifact identity that no longer matches runtime bytes.
    malformed = tmp_path / "cases.jsonl"
    _ = malformed.write_text('{"case_id":', encoding="utf-8")
    # When/Then: malformed input is rejected at its Pydantic boundary.
    with pytest.raises(EvaluationDataError):
        _ = load_diagnosis_cases(malformed)
    provenance = ArtifactProvenance(
        source_commit_sha="1" * 40,
        source_committed_at="2026-08-28T00:00:00Z",
        runtime_tree_hash="2" * 64,
        inputs=(FileDigest(path="fixture", sha256="3" * 64, schema_version="1.0"),),
        generator_invocation=("python", "scripts/run_benchmark.py"),
        seed=20270827,
        split=EvaluationSplit.HELDOUT,
        schema_version="1.0",
    )
    with pytest.raises(FreshnessError):
        verify_provenance_identity(provenance, current_runtime_tree_hash="4" * 64)
