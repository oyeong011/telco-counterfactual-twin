"""Exact Git status/diff contracts for canonical evaluation artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum, unique
from typing import TYPE_CHECKING, Annotated, Final, override

from pydantic import Field

from telco_twin.domain._contract import StrictContract

if TYPE_CHECKING:
    from pathlib import Path


@unique
class EvaluationArtifactFile(StrEnum):
    """The sole canonical Task-6 output file set."""

    COUNTERFACTUAL = "counterfactual.json"
    DIAGNOSIS_SUMMARY = "diagnosis-summary.json"
    DIAGNOSIS = "diagnosis.jsonl"
    REPLAY = "replay-hashes.json"
    SAFETY = "safety-gate.json"


CANONICAL_EVAL_DIRECTORY: Final = "artifacts/eval"
CANONICAL_EVAL_OUTPUTS: Final = tuple(
    f"{CANONICAL_EVAL_DIRECTORY}/{artifact.value}" for artifact in EvaluationArtifactFile
)
CANONICAL_EVAL_FILENAMES: Final = tuple(artifact.value for artifact in EvaluationArtifactFile)
PORCELAIN_ROW_PREFIX_LENGTH: Final = 4


class GitStatusEntry(StrictContract):
    """One porcelain-v1 XY row with optional rename/copy origin."""

    index_status: Annotated[str, Field(min_length=1, max_length=1)]
    worktree_status: Annotated[str, Field(min_length=1, max_length=1)]
    path: str
    original_path: str | None = None


class GitDiffEntry(StrictContract):
    """One `git diff --name-status -z` path transition."""

    status: str
    path: str
    original_path: str | None = None


@dataclass(frozen=True, slots=True)
class GitEvidenceError(Exception):
    """Git output is malformed or violates the exact artifact policy."""

    detail: str

    @override
    def __str__(self) -> str:
        return f"dirty-worktree: {self.detail}"


def _parts(output: str) -> tuple[str, ...]:
    parts = output.split("\0")
    return tuple(parts[:-1] if parts and parts[-1] == "" else parts)


def parse_porcelain_status_z(output: str) -> tuple[GitStatusEntry, ...]:
    """Parse NUL-delimited porcelain rows without losing XY or path bytes."""
    parts = _parts(output)
    entries: list[GitStatusEntry] = []
    index = 0
    while index < len(parts):
        row = parts[index]
        if len(row) < PORCELAIN_ROW_PREFIX_LENGTH or row[2] != " ":
            detail = "malformed porcelain status"
            raise GitEvidenceError(detail)
        xy = row[:2]
        path = row[3:]
        index += 1
        original: str | None = None
        if "R" in xy or "C" in xy:
            if index >= len(parts):
                detail = "rename/copy origin missing"
                raise GitEvidenceError(detail)
            original = parts[index]
            index += 1
        entries.append(
            GitStatusEntry(
                index_status=xy[0],
                worktree_status=xy[1],
                path=path,
                original_path=original,
            )
        )
    return tuple(entries)


def parse_name_status_z(output: str) -> tuple[GitDiffEntry, ...]:
    """Parse NUL-delimited commit diff paths including rename/copy pairs."""
    parts = _parts(output)
    entries: list[GitDiffEntry] = []
    index = 0
    while index < len(parts):
        status = parts[index]
        index += 1
        if index >= len(parts):
            detail = "diff path missing"
            raise GitEvidenceError(detail)
        first_path = parts[index]
        index += 1
        original: str | None = None
        path = first_path
        if status.startswith(("R", "C")):
            if index >= len(parts):
                detail = "diff rename/copy target missing"
                raise GitEvidenceError(detail)
            original = first_path
            path = parts[index]
            index += 1
        entries.append(GitDiffEntry(status=status, path=path, original_path=original))
    return tuple(entries)


def output_is_canonical(repo_root: Path, output: Path) -> bool:
    """Resolve one output and compare it to the sole canonical directory."""
    canonical = (repo_root / CANONICAL_EVAL_DIRECTORY).resolve(strict=False)
    return output.resolve(strict=False) == canonical


def _exact_paths(entries: tuple[GitStatusEntry, ...]) -> bool:
    return len(entries) == len(CANONICAL_EVAL_OUTPUTS) and {entry.path for entry in entries} == set(
        CANONICAL_EVAL_OUTPUTS
    )


def require_generation_worktree(
    entries: tuple[GitStatusEntry, ...],
    *,
    canonical_output: bool,
) -> None:
    """Allow only clean state or exact unstaged D/M canonical transitions."""
    if not canonical_output:
        detail = "noncanonical benchmark output"
        raise GitEvidenceError(detail)
    if not entries:
        return
    valid = _exact_paths(entries) and all(
        entry.index_status == " "
        and entry.worktree_status in {"D", "M"}
        and entry.original_path is None
        for entry in entries
    )
    if not valid:
        raise GitEvidenceError(",".join(entry.path for entry in entries))


def require_acceptance_worktree(entries: tuple[GitStatusEntry, ...]) -> None:
    """Allow clean B or exact unstaged canonical modifications generated at A."""
    if not entries:
        return
    valid = _exact_paths(entries) and all(
        entry.index_status == " " and entry.worktree_status == "M" and entry.original_path is None
        for entry in entries
    )
    if not valid:
        raise GitEvidenceError(",".join(entry.path for entry in entries))


def require_exact_source_diff(
    source_sha: str,
    head_sha: str,
    entries: tuple[GitDiffEntry, ...],
) -> None:
    """Require no diff at A and exactly five artifact-only A→B transitions."""
    if head_sha == source_sha:
        if entries:
            detail = "source commit has a nonempty self-diff"
            raise GitEvidenceError(detail)
        return
    valid = len(entries) == len(CANONICAL_EVAL_OUTPUTS) and {
        entry.path for entry in entries
    } == set(CANONICAL_EVAL_OUTPUTS)
    valid = valid and all(
        entry.status in {"A", "M"} and entry.original_path is None for entry in entries
    )
    if not valid:
        raise GitEvidenceError(",".join(entry.path for entry in entries))
