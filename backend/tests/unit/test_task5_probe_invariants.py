"""Manual probe pass-artifact invariant regressions."""

import pytest
from pydantic import ValidationError

from telco_twin.safety.local_policy import LOCAL_POLICY_DEFINITION_HASH
from telco_twin.state.probe_evidence import (
    PROBE_CONTRACT_HASH,
    PROBE_INVOCATION_ID,
    PROBE_SEED,
    CleanupEvidence,
    ConcurrencyEvidence,
    NegativeEvidence,
    PositiveEvidence,
    ProbeArtifact,
    ProbeArtifactPayload,
    ProbeArtifactStaleError,
    ProbeInputs,
    ProbeProvenance,
    build_probe_artifact,
    probe_schema_hash,
    validate_probe_artifact_json,
)


def _valid_negative() -> NegativeEvidence:
    return NegativeEvidence(
        replay_code="nonce-replayed",
        epoch_code="demo_session_lost",
        malformed_code="demo_token_invalid",
        unsafe_patch_code="patch-parameter-range",
        stale_policy_code="observation-stale",
        unsimulated_policy_code=("patch-hash-missing,simulation-hash-missing,simulation-missing"),
        forged_proof_code="approval-signature-invalid",
        dirty_baseline_code="manifest-integrity",
        expired_proof_code="approval-expired",
        cross_session_code="certificate-binding-mismatch",
    )


def _valid_positive() -> PositiveEvidence:
    return PositiveEvidence(
        baseline_hash_before="a" * 64,
        baseline_hash_after="a" * 64,
        candidate_hash="b" * 64,
        comparison_hash="c" * 64,
        policy_hash="d" * 64,
        certificate_hash="e" * 64,
        proof_hash="1" * 64,
        evidence_snapshot_hash="f" * 64,
        approval_state="approved",
        offline_chain_verified=True,
    )


def _payload(git_sha: str = "a" * 40) -> ProbeArtifactPayload:
    return ProbeArtifactPayload(
        schema_version="2.0",
        result="pass",
        provenance=ProbeProvenance(
            git_sha=git_sha,
            invocation_id=PROBE_INVOCATION_ID,
            seed=PROBE_SEED,
            schema_hash=probe_schema_hash(),
            contract_hash=PROBE_CONTRACT_HASH,
            policy_hash=LOCAL_POLICY_DEFINITION_HASH,
            inputs=ProbeInputs(
                manifest_hash="1" * 64,
                topology_hash="2" * 64,
                observation_hash="3" * 64,
                patch_hash="4" * 64,
            ),
        ),
        positive=_valid_positive(),
        negative=_valid_negative(),
        concurrency=ConcurrencyEvidence(
            requests=12,
            original_appends=1,
            replays=11,
            event_count=6,
        ),
        cleanup=CleanupEvidence(
            external_resources_created=False,
            in_memory_only=True,
            cancellation_required=False,
        ),
    )


@pytest.mark.parametrize(
    "field_name",
    [
        "replay_code",
        "epoch_code",
        "malformed_code",
        "unsafe_patch_code",
        "stale_policy_code",
        "unsimulated_policy_code",
        "forged_proof_code",
        "dirty_baseline_code",
        "expired_proof_code",
        "cross_session_code",
    ],
)
def test_probe_rejects_missing_required_negative_code(field_name: str) -> None:
    broken = _valid_negative().model_copy(update={field_name: "missing"})
    with pytest.raises(ValidationError):
        _ = NegativeEvidence.model_validate_json(broken.model_dump_json())


@pytest.mark.parametrize(
    "field_name",
    [
        "replay_code",
        "epoch_code",
        "malformed_code",
        "unsafe_patch_code",
        "stale_policy_code",
        "unsimulated_policy_code",
        "forged_proof_code",
        "dirty_baseline_code",
        "expired_proof_code",
        "cross_session_code",
    ],
)
def test_probe_rejects_removed_required_negative_code(field_name: str) -> None:
    payload = _valid_negative().model_dump_json(exclude={field_name})
    with pytest.raises(ValidationError):
        _ = NegativeEvidence.model_validate_json(payload)


def test_probe_rejects_missing_approval_proof_hash() -> None:
    broken = _valid_positive().model_copy(update={"proof_hash": "0" * 64})
    with pytest.raises(ValidationError):
        _ = PositiveEvidence.model_validate_json(broken.model_dump_json())


def test_probe_rejects_changed_baseline_hash() -> None:
    broken = _valid_positive().model_copy(update={"baseline_hash_after": "b" * 64})
    with pytest.raises(ValidationError):
        _ = PositiveEvidence.model_validate_json(broken.model_dump_json())


def test_probe_rejects_incomplete_concurrency_observable() -> None:
    with pytest.raises(ValidationError):
        _ = ConcurrencyEvidence(
            requests=12,
            original_appends=1,
            replays=10,
            event_count=6,
        )


def test_probe_accepts_only_complete_self_hashed_pass_artifact() -> None:
    artifact = build_probe_artifact(_payload())
    assert ProbeArtifact.model_validate_json(artifact.model_dump_json()) == artifact


def test_probe_rejects_tampered_payload_without_matching_self_hash() -> None:
    artifact = build_probe_artifact(_payload())
    tampered = artifact.model_copy(
        update={"positive": artifact.positive.model_copy(update={"candidate_hash": "9" * 64})}
    )
    with pytest.raises(ValidationError, match="artifact hash mismatch"):
        _ = ProbeArtifact.model_validate_json(tampered.model_dump_json())


def test_probe_rejects_self_consistent_artifact_from_stale_git_sha() -> None:
    artifact = build_probe_artifact(_payload("a" * 40))
    with pytest.raises(ProbeArtifactStaleError):
        _ = validate_probe_artifact_json(artifact.model_dump_json(), "b" * 40)
