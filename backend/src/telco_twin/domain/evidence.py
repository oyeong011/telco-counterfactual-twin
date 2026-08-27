"""Portable evidence-card contract for deterministic Twin artifacts."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from ._contract import (
    ContractId,
    GitCommitSha,
    RootContract,
    SafeKey,
    Seed,
    Sha256Hex,
    UtcTimestamp,
)


class EvidenceCard(RootContract):
    """Hashes and provenance for a synthetic, non-executing decision artifact."""

    evidence_id: ContractId
    session_id: ContractId
    scenario_hash: Sha256Hex
    patch_hash: Sha256Hex
    simulation_hash: Sha256Hex
    policy_hash: Sha256Hex
    approval_proof_hash: Sha256Hex | None
    seed: Seed
    source_commit_sha: GitCommitSha
    contract_hashes: Annotated[dict[SafeKey, Sha256Hex], Field(min_length=1, max_length=32)]
    generated_at: UtcTimestamp
