"""Strict self-hashed pass artifact for the Task5 manual probe."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Annotated, ClassVar, Final, Literal, Self, override

from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter, model_validator

from telco_twin.domain._validation import fail_validation
from telco_twin.domain.canonical import canonical_json_bytes, canonical_model_bytes
from telco_twin.safety.local_policy import LOCAL_POLICY_DEFINITION_HASH

ProbeHash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
ProbeGitSha = Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
PROBE_INVOCATION_ID: Final = "task5-safety-probe-v2"
PROBE_SEED: Final = 91
EXPECTED_REQUESTS: Final = 12
EXPECTED_REPLAYS: Final = 11
EXPECTED_EVENT_COUNT: Final = 6
EXPECTED_NEGATIVE_CODES: Final = (
    "nonce-replayed",
    "demo_session_lost",
    "demo_token_invalid",
    "patch-parameter-range",
    "observation-stale",
    "patch-hash-missing,simulation-hash-missing,simulation-missing",
    "approval-signature-invalid",
    "manifest-integrity",
    "approval-expired",
    "certificate-binding-mismatch",
)
JSON_ADAPTER: Final[TypeAdapter[JsonValue]] = TypeAdapter(JsonValue)


class _ArtifactModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)


class PositiveEvidence(_ArtifactModel):
    """Required hashes and approval observables for the positive flow."""

    baseline_hash_before: ProbeHash
    baseline_hash_after: ProbeHash
    candidate_hash: ProbeHash
    comparison_hash: ProbeHash
    policy_hash: ProbeHash
    certificate_hash: ProbeHash
    proof_hash: ProbeHash
    evidence_snapshot_hash: ProbeHash
    approval_state: Literal["approved"]
    offline_chain_verified: Literal[True]

    @model_validator(mode="after")
    def positive_invariants_hold(self) -> Self:
        """Reject baseline mutation and proof-hash masking."""
        if self.baseline_hash_before != self.baseline_hash_after:
            fail_validation("probe_baseline_changed", "probe baseline hash changed")
        if self.proof_hash == "0" * 64:
            fail_validation("probe_proof_missing", "probe approval proof hash is missing")
        return self


class NegativeEvidence(_ArtifactModel):
    """Exact stable codes required before the probe can claim pass."""

    replay_code: str
    epoch_code: str
    malformed_code: str
    unsafe_patch_code: str
    stale_policy_code: str
    unsimulated_policy_code: str
    forged_proof_code: str
    dirty_baseline_code: str
    expired_proof_code: str
    cross_session_code: str

    @model_validator(mode="after")
    def exact_negative_codes_are_present(self) -> Self:
        """Reject any missing or changed required negative code."""
        if tuple(self.model_dump().values()) != EXPECTED_NEGATIVE_CODES:
            fail_validation("probe_negative_missing", "required probe negative is missing")
        return self


class ConcurrencyEvidence(_ArtifactModel):
    """Exact bounded same-key race result."""

    requests: int
    original_appends: int
    replays: int
    event_count: int

    @model_validator(mode="after")
    def exact_race_observables_are_present(self) -> Self:
        """Require the complete bounded same-key race result."""
        if (
            self.requests != EXPECTED_REQUESTS
            or self.original_appends != 1
            or self.replays != EXPECTED_REPLAYS
            or self.event_count != EXPECTED_EVENT_COUNT
        ):
            fail_validation("probe_concurrency_incomplete", "probe race evidence is incomplete")
        return self


class CleanupEvidence(_ArtifactModel):
    """Proof that the manual flow had no external resource lifecycle."""

    external_resources_created: Literal[False]
    in_memory_only: Literal[True]
    cancellation_required: Literal[False]


class ProbeInputs(_ArtifactModel):
    """Exact immutable inputs used by the successful flow."""

    manifest_hash: ProbeHash
    topology_hash: ProbeHash
    observation_hash: ProbeHash
    patch_hash: ProbeHash


class ProbeProvenance(_ArtifactModel):
    """Reviewed code/command/contracts bound into the artifact."""

    git_sha: ProbeGitSha
    invocation_id: Literal["task5-safety-probe-v2"]
    seed: Literal[91]
    schema_hash: ProbeHash
    contract_hash: ProbeHash
    policy_hash: ProbeHash
    inputs: ProbeInputs

    @model_validator(mode="after")
    def contract_identities_match(self) -> Self:
        """Reject stale command, schema, contract, or policy identity."""
        if (
            self.schema_hash != probe_schema_hash()
            or self.contract_hash != PROBE_CONTRACT_HASH
            or self.policy_hash != LOCAL_POLICY_DEFINITION_HASH
        ):
            fail_validation("probe_contract_stale", "probe contract identity is stale")
        return self


class ProbeArtifactPayload(_ArtifactModel):
    """All pass evidence before the outer self-hash is added."""

    schema_version: Literal["2.0"]
    result: Literal["pass"]
    provenance: ProbeProvenance
    positive: PositiveEvidence
    negative: NegativeEvidence
    concurrency: ConcurrencyEvidence
    cleanup: CleanupEvidence


class ProbeArtifact(ProbeArtifactPayload):
    """Pass artifact whose RFC8785 payload hash is validated on parse."""

    artifact_hash: ProbeHash

    @model_validator(mode="after")
    def artifact_hash_matches_payload(self) -> Self:
        """Recompute the RFC8785 self-hash during every parse."""
        expected = hashlib.sha256(
            canonical_model_bytes(self, exclude=frozenset({"artifact_hash"}))
        ).hexdigest()
        if self.artifact_hash != expected:
            fail_validation("probe_artifact_hash", "probe artifact hash mismatch")
        return self


class _ProbeContract(_ArtifactModel):
    invocation_id: Literal["task5-safety-probe-v2"]
    seed: Literal[91]
    negative_codes: tuple[str, ...]
    race: tuple[int, int, int, int]


PROBE_CONTRACT: Final = _ProbeContract(
    invocation_id=PROBE_INVOCATION_ID,
    seed=PROBE_SEED,
    negative_codes=EXPECTED_NEGATIVE_CODES,
    race=(EXPECTED_REQUESTS, 1, EXPECTED_REPLAYS, EXPECTED_EVENT_COUNT),
)
PROBE_CONTRACT_HASH: Final[ProbeHash] = hashlib.sha256(
    canonical_model_bytes(PROBE_CONTRACT)
).hexdigest()


def probe_schema_hash() -> ProbeHash:
    """Hash the canonical payload JSON Schema used by this artifact version."""
    schema = JSON_ADAPTER.validate_python(ProbeArtifactPayload.model_json_schema())
    return hashlib.sha256(canonical_json_bytes(schema)).hexdigest()


def build_probe_artifact(payload: ProbeArtifactPayload) -> ProbeArtifact:
    """Add the exact RFC8785 self-hash to one complete payload."""
    return ProbeArtifact(
        schema_version=payload.schema_version,
        result=payload.result,
        provenance=payload.provenance,
        positive=payload.positive,
        negative=payload.negative,
        concurrency=payload.concurrency,
        cleanup=payload.cleanup,
        artifact_hash=hashlib.sha256(canonical_model_bytes(payload)).hexdigest(),
    )


@dataclass(frozen=True, slots=True)
class ProbeArtifactStaleError(Exception):
    """Artifact commit identity differs from the reviewed checkout."""

    expected: ProbeGitSha
    actual: ProbeGitSha

    @override
    def __str__(self) -> str:
        return "probe-artifact-git-sha-stale"


def validate_probe_artifact_json(encoded: str, expected_git_sha: ProbeGitSha) -> ProbeArtifact:
    """Parse, self-hash, and require the exact reviewed full git SHA."""
    artifact = ProbeArtifact.model_validate_json(encoded)
    if artifact.provenance.git_sha != expected_git_sha:
        raise ProbeArtifactStaleError(expected_git_sha, artifact.provenance.git_sha)
    return artifact
