"""Manual probe pass-artifact invariant regressions."""

import pytest
from pydantic import ValidationError

from telco_twin.approval import crypto as approval_crypto
from telco_twin.state.probe_evidence import (
    CleanupEvidence,
    ConcurrencyEvidence,
    NegativeEvidence,
    PositiveEvidence,
    ProbeArtifact,
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
    # Given: a pass-shaped negative evidence object with one missing result.
    broken = _valid_negative().model_copy(update={field_name: "missing"})
    # When/Then: boundary parsing refuses the pass artifact.
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
    # Given: a serialized pass-shaped negative object missing one required field.
    payload = _valid_negative().model_dump_json(exclude={field_name})
    # When/Then: removal cannot produce a valid pass artifact.
    with pytest.raises(ValidationError):
        _ = NegativeEvidence.model_validate_json(payload)


def test_probe_requires_expired_and_cross_session_negative_fields() -> None:
    # Given: the durable pass-artifact schema.
    fields = frozenset(NegativeEvidence.model_fields)
    # When/Then: required approval negatives are structurally mandatory.
    assert {"expired_proof_code", "cross_session_code"} <= fields


def test_probe_rejects_missing_approval_proof_hash() -> None:
    # Given: approved evidence whose missing proof hash was masked as zeroes.
    # When/Then: a valid-looking fallback cannot enter a pass artifact.
    with pytest.raises(ValidationError):
        _ = PositiveEvidence(
            baseline_hash_before="a" * 64,
            baseline_hash_after="a" * 64,
            candidate_hash="b" * 64,
            comparison_hash="c" * 64,
            policy_hash="d" * 64,
            certificate_hash="e" * 64,
            proof_hash="0" * 64,
            evidence_snapshot_hash="f" * 64,
            approval_state="approved",
            offline_chain_verified=True,
        )


def test_probe_rejects_changed_baseline_hash() -> None:
    # Given/When/Then: baseline mutation cannot enter a pass artifact.
    with pytest.raises(ValidationError):
        _ = PositiveEvidence(
            baseline_hash_before="a" * 64,
            baseline_hash_after="b" * 64,
            candidate_hash="c" * 64,
            comparison_hash="d" * 64,
            policy_hash="e" * 64,
            certificate_hash="f" * 64,
            proof_hash="1" * 64,
            evidence_snapshot_hash="2" * 64,
            approval_state="approved",
            offline_chain_verified=True,
        )


def test_probe_rejects_incomplete_concurrency_observable() -> None:
    # Given: concurrency evidence that lost one expected replay.
    # When/Then: result=pass cannot be built from incomplete race evidence.
    with pytest.raises(ValidationError):
        _ = ConcurrencyEvidence(
            requests=12,
            original_appends=1,
            replays=10,
            event_count=6,
        )


def test_probe_accepts_only_complete_pass_artifact() -> None:
    # Given: every exact positive, negative, race, and cleanup observable.
    artifact = ProbeArtifact(
        schema_version="1.0",
        result="pass",
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
    # When/Then: complete evidence is the sole pass-shaped artifact.
    assert artifact.result == "pass"


def test_unused_public_key_fingerprint_helper_is_absent() -> None:
    # Given: the production approval crypto module.
    # When/Then: only helpers used by the real trust path remain public.
    assert not hasattr(approval_crypto, "public_key_fingerprint")
