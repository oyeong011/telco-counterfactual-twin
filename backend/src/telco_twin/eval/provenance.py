"""Git-bound evaluation provenance and runtime-tree freshness guards."""

from __future__ import annotations

import hashlib
import sys
from dataclasses import dataclass
from enum import StrEnum, unique
from typing import TYPE_CHECKING, Final, override

from telco_twin.domain._contract import GitCommitSha, RootContract, UtcTimestamp
from telco_twin.eval.git_evidence import (
    CANONICAL_EVAL_OUTPUTS,
    GitDiffEntry,
    GitEvidenceError,
    GitStatusEntry,
    output_is_canonical,
    require_acceptance_worktree,
    require_exact_source_diff,
    require_generation_worktree,
)
from telco_twin.eval.metrics import (
    ArtifactProvenance,
    EvaluationSplit,
    FileDigest,
)

if TYPE_CHECKING:
    from pathlib import Path

    from telco_twin.domain._contract import Sha256Hex

RUNTIME_GLOBS: Final = (
    "backend/src/telco_twin/eval/**/*.py",
    "backend/src/telco_twin/simulator/**/*.py",
    "backend/src/telco_twin/counterfactual/**/*.py",
    "backend/src/telco_twin/safety/**/*.py",
    "backend/src/telco_twin/data/**/*.py",
    "backend/src/telco_twin/domain/**/*.py",
    "backend/fixtures/eval/*",
    "specs/schemas/*.json",
    "backend/pyproject.toml",
    "backend/uv.lock",
    "scripts/check_split_leakage.py",
    "scripts/run_benchmark.py",
    "scripts/assert_acceptance.py",
    "scripts/download_recorded_model.py",
)


@unique
class ProvenanceErrorCode(StrEnum):
    """Stable provenance failures exposed by generation and acceptance."""

    DIRTY_WORKTREE = "dirty-worktree"
    GIT_FAILURE = "git-failure"
    PYTHON_RUNTIME = "python-runtime"
    RUNTIME_TREE = "runtime-tree-mismatch"
    SOURCE_COMMIT = "source-commit-invalid"
    INPUT_DIGEST = "input-digest-mismatch"


DirtyWorktreeError = GitEvidenceError


@dataclass(frozen=True, slots=True)
class FreshnessError(Exception):
    """Generated evidence no longer matches its recorded source identity."""

    code: ProvenanceErrorCode
    detail: str

    @override
    def __str__(self) -> str:
        return f"{self.code.value}: {self.detail}"


@dataclass(frozen=True, slots=True)
class ProvenanceRequest:
    """Inputs needed to bind one clean source commit to generated evidence."""

    repo_root: Path
    input_paths: tuple[Path, ...]
    generator_invocation: tuple[str, ...]
    output_path: Path
    seed: int
    split: EvaluationSplit


class RepositoryState(RootContract):
    """Typed Git facts collected by a script outside product code."""

    head_sha: GitCommitSha
    source_sha: GitCommitSha
    source_tree_sha: GitCommitSha
    source_committed_at: UtcTimestamp
    source_is_ancestor: bool
    status_entries: tuple[GitStatusEntry, ...]
    source_diff: tuple[GitDiffEntry, ...]


def require_clean_worktree(entries: tuple[GitStatusEntry, ...]) -> None:
    """Reject any status row when no canonical generation exception applies."""
    if entries:
        raise GitEvidenceError(",".join(entry.path for entry in entries))


def _sha256(path: Path) -> Sha256Hex:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _runtime_files(repo_root: Path) -> tuple[Path, ...]:
    paths = {
        path
        for pattern in RUNTIME_GLOBS
        for path in repo_root.glob(pattern)
        if path.is_file() and "__pycache__" not in path.parts
    }
    return tuple(sorted(paths, key=lambda path: path.relative_to(repo_root).as_posix()))


def runtime_tree_digest(repo_root: Path) -> Sha256Hex:
    """Hash sorted path-NUL-file-hash records for the evaluation runtime."""
    digest = hashlib.sha256()
    for path in _runtime_files(repo_root):
        if path.is_symlink():
            raise FreshnessError(ProvenanceErrorCode.RUNTIME_TREE, "runtime symlink rejected")
        relative = path.relative_to(repo_root).as_posix()
        digest.update(f"{relative}\0{_sha256(path)}\n".encode())
    return digest.hexdigest()


def _file_digest(repo_root: Path, path: Path) -> FileDigest:
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(repo_root.resolve()).as_posix()
    except ValueError as error:
        raise FreshnessError(
            ProvenanceErrorCode.INPUT_DIGEST, "input outside repository"
        ) from error
    if resolved.is_symlink() or not resolved.is_file():
        raise FreshnessError(ProvenanceErrorCode.INPUT_DIGEST, relative)
    return FileDigest(path=relative, sha256=_sha256(resolved), schema_version="1.0")


def capture_provenance(
    request: ProvenanceRequest,
    repository: RepositoryState,
) -> ArtifactProvenance:
    """Bind generation to a clean commit, runtime tree, invocation, and inputs."""
    require_generation_worktree(
        repository.status_entries,
        canonical_output=output_is_canonical(request.repo_root, request.output_path),
    )
    if sys.version_info[:2] != (3, 12):
        raise FreshnessError(ProvenanceErrorCode.PYTHON_RUNTIME, sys.version.split()[0])
    if repository.head_sha != repository.source_sha or not repository.source_is_ancestor:
        raise FreshnessError(ProvenanceErrorCode.SOURCE_COMMIT, repository.source_sha)
    return ArtifactProvenance(
        source_commit_sha=repository.source_sha,
        source_tree_sha=repository.source_tree_sha,
        source_committed_at=repository.source_committed_at,
        runtime_tree_hash=runtime_tree_digest(request.repo_root),
        expected_output_files=CANONICAL_EVAL_OUTPUTS,
        inputs=tuple(_file_digest(request.repo_root, path) for path in request.input_paths),
        generator_invocation=request.generator_invocation,
        seed=request.seed,
        split=request.split,
        schema_version="1.0",
    )


def verify_provenance_identity(
    provenance: ArtifactProvenance,
    *,
    current_runtime_tree_hash: Sha256Hex,
) -> None:
    """Reject an artifact whose current runtime identity differs from source A."""
    if provenance.runtime_tree_hash != current_runtime_tree_hash:
        raise FreshnessError(ProvenanceErrorCode.RUNTIME_TREE, "runtime tree changed")


def verify_provenance(
    repo_root: Path,
    provenance: ArtifactProvenance,
    repository: RepositoryState,
) -> None:
    """Recompute runtime/input identities and require source A to be an ancestor."""
    require_acceptance_worktree(repository.status_entries)
    verify_provenance_identity(
        provenance,
        current_runtime_tree_hash=runtime_tree_digest(repo_root),
    )
    if (
        repository.source_sha != provenance.source_commit_sha
        or provenance.source_tree_sha is None
        or repository.source_tree_sha != provenance.source_tree_sha
        or repository.source_committed_at != provenance.source_committed_at
        or not repository.source_is_ancestor
    ):
        raise FreshnessError(ProvenanceErrorCode.SOURCE_COMMIT, provenance.source_commit_sha)
    if provenance.expected_output_files != CANONICAL_EVAL_OUTPUTS:
        raise FreshnessError(ProvenanceErrorCode.SOURCE_COMMIT, "expected output set changed")
    require_exact_source_diff(
        provenance.source_commit_sha,
        repository.head_sha,
        repository.source_diff,
    )
    for recorded in provenance.inputs:
        current = _file_digest(repo_root, repo_root / recorded.path)
        if current != recorded:
            raise FreshnessError(ProvenanceErrorCode.INPUT_DIGEST, recorded.path)
