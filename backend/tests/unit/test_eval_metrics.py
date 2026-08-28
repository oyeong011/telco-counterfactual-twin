"""Frozen metric denominators and canonical generation-state tests."""

from __future__ import annotations

import pytest

from telco_twin.domain.scenario import FaultFamily
from telco_twin.eval.git_evidence import (
    CANONICAL_EVAL_OUTPUTS,
    GitEvidenceError,
    GitStatusEntry,
    parse_porcelain_status_z,
    require_generation_worktree,
)
from telco_twin.eval.metrics import (
    DiagnosisOutcome,
    EvaluationContractError,
    EvaluationSplit,
    SafetyExpectation,
    SafetyOutcome,
    score_heldout,
    score_safety,
)


def _perfect_heldout() -> tuple[DiagnosisOutcome, ...]:
    return tuple(
        DiagnosisOutcome(
            case_id=f"heldout-{family.value}-{index}",
            split=EvaluationSplit.HELDOUT,
            expected=family,
            predicted=family,
        )
        for family in FaultFamily
        for index in range(6)
    )


def test_heldout_macro_f1_uses_exact_six_by_six_denominator() -> None:
    # Given: exactly six held-out predictions for each frozen fault family.
    outcomes = _perfect_heldout()
    # When: the six-class metric is scored.
    result = score_heldout(outcomes)
    # Then: only 36 held-out cases enter the perfect macro-F1.
    assert result.evaluated_count == 36
    assert result.macro_f1 == 1.0
    assert tuple(item.support for item in result.per_class) == (6, 6, 6, 6, 6, 6)


@pytest.mark.parametrize("drift", ["missing", "development", "class-skew"])
def test_heldout_metric_rejects_denominator_or_split_drift(drift: str) -> None:
    # Given: an otherwise valid corpus with one protocol violation.
    outcomes = list(_perfect_heldout())
    match drift:  # noqa: MATCH_OK
        case "missing":
            _ = outcomes.pop()
        case "development":
            first = outcomes[0]
            assert isinstance(first, DiagnosisOutcome)
            outcomes[0] = first.model_copy(update={"split": EvaluationSplit.DEVELOPMENT})
        case "class-skew":
            first = outcomes[0]
            assert isinstance(first, DiagnosisOutcome)
            outcomes[0] = first.model_copy(update={"expected": FaultFamily.BACKHAUL_DEGRADATION})
        case _:
            raise AssertionError(drift)
    # When/Then: scoring fails rather than silently changing the denominator.
    with pytest.raises(EvaluationContractError):
        _ = score_heldout(tuple(outcomes))


def test_safety_metric_locks_twenty_unsafe_and_twenty_safe() -> None:
    # Given: all unsafe patches blocked and exactly two safe patches falsely blocked.
    outcomes = tuple(
        SafetyOutcome(
            case_id=f"unsafe-{index}",
            expectation=SafetyExpectation.UNSAFE,
            blocked=True,
        )
        for index in range(20)
    ) + tuple(
        SafetyOutcome(
            case_id=f"safe-{index}",
            expectation=SafetyExpectation.SAFE,
            blocked=index < 2,
        )
        for index in range(20)
    )
    # When: the frozen safety denominator is scored.
    result = score_safety(outcomes)
    # Then: both numerators retain their exact independent denominators.
    assert result.unsafe_blocked == 20
    assert result.unsafe_denominator == 20
    assert result.safe_false_blocks == 2
    assert result.safe_denominator == 20


def test_safety_metric_rejects_denominator_drift() -> None:
    # Given: only 19 unsafe cases and 20 safe cases.
    outcomes = tuple(
        SafetyOutcome(
            case_id=f"unsafe-{index}",
            expectation=SafetyExpectation.UNSAFE,
            blocked=True,
        )
        for index in range(19)
    ) + tuple(
        SafetyOutcome(
            case_id=f"safe-{index}",
            expectation=SafetyExpectation.SAFE,
            blocked=False,
        )
        for index in range(20)
    )
    # When/Then: the missing unsafe case cannot shrink the acceptance denominator.
    with pytest.raises(EvaluationContractError):
        _ = score_safety(outcomes)


def _canonical_entries() -> tuple[GitStatusEntry, ...]:
    return tuple(
        GitStatusEntry(index_status=" ", worktree_status="D", path=path)
        for path in CANONICAL_EVAL_OUTPUTS
    )


def test_porcelain_z_parser_preserves_xy_paths_and_rename_origin() -> None:
    # Given: unstaged, staged, rename, and untracked NUL-delimited porcelain rows.
    raw = " D artifacts/eval/diagnosis.jsonl\0M  staged.txt\0R  new.txt\0old.txt\0?? extra\0"
    # When: status is parsed without line-oriented trimming.
    entries = parse_porcelain_status_z(raw)
    # Then: XY state, paths, and rename origin remain exact.
    assert tuple((item.index_status, item.worktree_status) for item in entries) == (
        (" ", "D"),
        ("M", " "),
        ("R", " "),
        ("?", "?"),
    )
    assert entries[2].path == "new.txt"
    assert entries[2].original_path == "old.txt"


def test_generation_allows_exact_unstaged_canonical_transitions() -> None:
    # Given: exactly five tracked canonical rows with unstaged D/M state.
    entries = list(_canonical_entries())
    entries[0] = entries[0].model_copy(update={"worktree_status": "M"})
    # When/Then: canonical generation accepts the exact mixed transition set.
    require_generation_worktree(tuple(entries), canonical_output=True)


@pytest.mark.parametrize(
    "variant",
    ["staged", "untracked", "nested", "unrelated", "rename", "arbitrary-output"],
)
def test_generation_rejects_noncanonical_status_or_output(variant: str) -> None:
    # Given: one violation of the exact canonical unstaged-five policy.
    entries = list(_canonical_entries())
    canonical_output = True
    match variant:  # noqa: MATCH_OK
        case "staged":
            entries[0] = entries[0].model_copy(update={"index_status": "M", "worktree_status": " "})
        case "untracked":
            entries.append(GitStatusEntry(index_status="?", worktree_status="?", path="extra"))
        case "nested":
            entries[0] = entries[0].model_copy(update={"path": "artifacts/eval/nested/x"})
        case "unrelated":
            entries[0] = entries[0].model_copy(update={"path": "README.md"})
        case "rename":
            entries[0] = entries[0].model_copy(
                update={"index_status": "R", "worktree_status": " ", "original_path": "old"}
            )
        case "arbitrary-output":
            canonical_output = False
        case _:
            raise AssertionError(variant)
    # When/Then: generation fails closed instead of broadening an output allowlist.
    with pytest.raises(GitEvidenceError):
        require_generation_worktree(tuple(entries), canonical_output=canonical_output)
