"""Git, contract, and immutable-input provenance for the Task5 probe."""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

from pydantic import TypeAdapter
from telco_twin.domain._contract import GitCommitSha, Sha256Hex
from telco_twin.domain.canonical import canonical_model_bytes
from telco_twin.safety.local_policy import LOCAL_POLICY_DEFINITION_HASH
from telco_twin.state.probe_evidence import (
    PROBE_CONTRACT_HASH,
    PROBE_INVOCATION_ID,
    PROBE_SEED,
    ProbeInputs,
    ProbeProvenance,
    probe_schema_hash,
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


def current_git_sha() -> GitCommitSha:
    """Resolve the exact reviewed full commit without exposing command output."""
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    )
    return GIT_SHA_ADAPTER.validate_python(result.stdout.strip())


def build_probe_provenance(inputs: ProbeRunInputs) -> ProbeProvenance:
    """Bind current commit, command contract, policy, and actual input hashes."""
    observation_hash = hashlib.sha256(
        canonical_model_bytes(inputs.observation)
    ).hexdigest()
    return ProbeProvenance(
        git_sha=current_git_sha(),
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
