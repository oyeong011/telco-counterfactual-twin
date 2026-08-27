"""Git, contract, and immutable-input provenance for the Task5 probe."""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal, override

from pydantic import TypeAdapter
from telco_twin.domain._contract import GitCommitSha, Sha256Hex
from telco_twin.domain.canonical import canonical_model_bytes
from telco_twin.safety.local_policy import LOCAL_POLICY_DEFINITION_HASH
from telco_twin.state.probe_evidence import (
    CLEAN_STATUS_HASH,
    PROBE_CONTRACT_HASH,
    PROBE_INVOCATION_ID,
    PROBE_SEED,
    ProbeArtifact,
    ProbeInputs,
    ProbeProvenance,
    probe_schema_hash,
    validate_probe_artifact_json,
)

if TYPE_CHECKING:
    from telco_twin.data.synthetic import SimulationManifest
    from telco_twin.simulator.network_model import NetworkObservation

REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[1]
GIT_SHA_ADAPTER: Final[TypeAdapter[GitCommitSha]] = TypeAdapter(GitCommitSha)


@dataclass(frozen=True, slots=True)
class ProbeRunInputs:
    """Actual immutable inputs whose hashes are bound into pass evidence."""

    manifest: SimulationManifest
    observation: NetworkObservation
    patch_hash: Sha256Hex


@dataclass(frozen=True, slots=True)
class ProbeRepositoryState:
    """Exact committed identity and canonical clean status evidence."""

    git_sha: GitCommitSha
    worktree_clean: Literal[True]
    status_hash: Sha256Hex


@dataclass(frozen=True, slots=True)
class ProbeArtifactWorktreeError(RuntimeError):
    """The target repository contains tracked, staged, or untracked changes."""

    @override
    def __str__(self) -> str:
        return "artifact-worktree-dirty"


def _git_output(repository_root: Path, arguments: tuple[str, ...]) -> bytes:
    result = subprocess.run(
        ["git", *arguments],
        cwd=repository_root,
        check=True,
        capture_output=True,
        timeout=5,
    )
    return result.stdout


def clean_repository_state(repository_root: Path) -> ProbeRepositoryState:
    """Require a clean porcelain-v1 status and bind the exact full HEAD."""
    status = _git_output(
        repository_root,
        ("status", "--porcelain=v1", "--untracked-files=all"),
    )
    if status:
        raise ProbeArtifactWorktreeError
    git_sha = GIT_SHA_ADAPTER.validate_python(
        _git_output(repository_root, ("rev-parse", "HEAD")).decode().strip()
    )
    return ProbeRepositoryState(
        git_sha=git_sha,
        worktree_clean=True,
        status_hash=hashlib.sha256(status).hexdigest(),
    )


def build_probe_provenance(
    inputs: ProbeRunInputs,
    repository_root: Path = REPOSITORY_ROOT,
) -> ProbeProvenance:
    """Bind current commit, command contract, policy, and actual input hashes."""
    repository = clean_repository_state(repository_root)
    observation_hash = hashlib.sha256(
        canonical_model_bytes(inputs.observation)
    ).hexdigest()
    return ProbeProvenance(
        git_sha=repository.git_sha,
        worktree_clean=repository.worktree_clean,
        status_hash=repository.status_hash,
        invocation_id=PROBE_INVOCATION_ID,
        seed=PROBE_SEED,
        schema_hash=probe_schema_hash(),
        contract_hash=PROBE_CONTRACT_HASH,
        policy_hash=LOCAL_POLICY_DEFINITION_HASH,
        inputs=ProbeInputs(
            manifest_hash=inputs.manifest.manifest_hash,
            topology_hash=inputs.manifest.topology_hash,
            observation_hash=observation_hash,
            patch_hash=inputs.patch_hash,
        ),
    )


def validate_local_probe_artifact_json(
    encoded: str,
    repository_root: Path = REPOSITORY_ROOT,
) -> ProbeArtifact:
    """Validate artifact hashes plus the live repository's clean exact HEAD."""
    repository = clean_repository_state(repository_root)
    artifact = validate_probe_artifact_json(encoded, repository.git_sha)
    if (
        artifact.provenance.worktree_clean is not True
        or artifact.provenance.status_hash != repository.status_hash
        or repository.status_hash != CLEAN_STATUS_HASH
    ):
        raise ProbeArtifactWorktreeError
    return artifact
