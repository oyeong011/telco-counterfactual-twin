"""Strict pass-artifact schema for the Task5 manual probe."""

from __future__ import annotations

from typing import Annotated, ClassVar, Final, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from telco_twin.domain._validation import fail_validation

ProbeHash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
EXPECTED_REQUESTS: Final = 12
EXPECTED_REPLAYS: Final = 11
EXPECTED_EVENT_COUNT: Final = 6


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
        """Reject pass artifacts missing any required stable negative."""
        valid = (
            self.replay_code == "nonce-replayed"
            and self.epoch_code == "demo_session_lost"
            and self.malformed_code == "demo_token_invalid"
            and self.unsafe_patch_code == "patch-parameter-range"
            and self.stale_policy_code == "observation-stale"
            and self.unsimulated_policy_code
            == "patch-hash-missing,simulation-hash-missing,simulation-missing"
            and self.forged_proof_code == "approval-signature-invalid"
            and self.dirty_baseline_code == "manifest-integrity"
            and self.expired_proof_code == "approval-expired"
            and self.cross_session_code == "certificate-binding-mismatch"
        )
        if not valid:
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


class ProbeArtifact(_ArtifactModel):
    """Pass artifact constructible only from every exact Task5 observable."""

    schema_version: Literal["1.0"]
    result: Literal["pass"]
    positive: PositiveEvidence
    negative: NegativeEvidence
    concurrency: ConcurrencyEvidence
    cleanup: CleanupEvidence
