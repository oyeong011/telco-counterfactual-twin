"""Local-policy, token, and store fail-closed edge tests."""

import hashlib
import hmac
import json

import anyio
import pytest
from pydantic import ValidationError

from telco_twin.domain.approval import encode_base64url
from telco_twin.domain.canonical import canonical_model_bytes
from telco_twin.safety.local_policy import (
    LocalPolicyInput,
    PolicyEvaluation,
    PolicyReason,
    evaluate_local_policy,
)
from telco_twin.simulator.metrics import ObservationQualityFlag, QualityAssessment
from telco_twin.state.demo_token import (
    DEMO_TOKEN_DOMAIN,
    DemoTokenClaims,
    DemoTokenCodec,
    DemoTokenFailureCode,
    DemoTokenIssue,
    DemoTokenIssueError,
    DemoTokenIssueErrorCode,
    DemoTokenKey,
    DemoTokenRejected,
)
from telco_twin.state.memory_store import DemoSessionStore
from telco_twin.state.store_models import (
    AppendEventRequest,
    EventAppendDenied,
    SessionAccessCode,
    SessionCreate,
    SessionCreateDenied,
)

from .test_local_policy import local_policy_input
from .test_memory_store import NOW, SECRET, store_event


def test_policy_result_rejects_altered_hash_and_inconsistent_eligibility() -> None:
    # Given: one valid hashed local policy result.
    valid = evaluate_local_policy(local_policy_input()).evidence
    altered = valid.model_dump(mode="json")
    altered["policy_hash"] = "0" * 64
    # When/Then: hash alteration and both eligibility inconsistencies fail validation.
    with pytest.raises(ValidationError, match="policy result hash mismatch"):
        _ = PolicyEvaluation.model_validate(altered)
    inconsistent = valid.model_copy(
        update={"reasons": (PolicyReason.UNSAFE_CONSTRAINT,), "policy_hash": "0" * 64}
    )
    inconsistent = inconsistent.model_copy(
        update={
            "policy_hash": hashlib.sha256(
                canonical_model_bytes(inconsistent, exclude=frozenset({"policy_hash"}))
            ).hexdigest()
        }
    )
    with pytest.raises(ValidationError, match="eligible policy result lacks"):
        _ = PolicyEvaluation.model_validate_json(inconsistent.model_dump_json())
    denied = evaluate_local_policy(
        LocalPolicyInput(
            quality=local_policy_input().quality,
            run=None,
            comparison=None,
        )
    ).evidence
    no_reasons = denied.model_copy(update={"reasons": (), "policy_hash": "0" * 64})
    no_reasons = no_reasons.model_copy(
        update={
            "policy_hash": hashlib.sha256(
                canonical_model_bytes(no_reasons, exclude=frozenset({"policy_hash"}))
            ).hexdigest()
        }
    )
    with pytest.raises(ValidationError, match="requires a reason"):
        _ = PolicyEvaluation.model_validate_json(no_reasons.model_dump_json())


def test_policy_covers_future_and_missing_simulator_reasons() -> None:
    # Given: a future observation over valid simulator provenance.
    policy_input = local_policy_input(
        quality=QualityAssessment(
            flags=(ObservationQualityFlag.FUTURE,),
            approval_eligible=False,
        )
    )
    # When: quality and missing simulator paths are evaluated.
    first = evaluate_local_policy(policy_input).evidence
    missing = evaluate_local_policy(
        LocalPolicyInput(quality=local_policy_input().quality, run=None, comparison=None)
    ).evidence
    # Then: both failure classes remain explicit.
    assert PolicyReason.OBSERVATION_FUTURE in first.reasons
    assert PolicyReason.SIMULATION_MISSING in missing.reasons


def _signed_token(payload: bytes, key: bytes) -> str:
    signature = hmac.new(key, DEMO_TOKEN_DOMAIN + payload, hashlib.sha256).digest()
    return f"{encode_base64url(payload)}.{encode_base64url(signature)}"


def test_demo_token_rejects_bad_ttl_key_nonce_and_time() -> None:
    # Given: malformed issuance boundaries.
    with pytest.raises(ValidationError, match="TTL must be 15 minutes"):
        _ = DemoTokenClaims(
            v=1,
            session_id="session-0001",
            startup_epoch="epoch-0001",
            issued_at="2026-08-27T00:00:00Z",
            expires_at="2026-08-27T00:14:59Z",
            nonce="AAECAwQFBgcICQoLDA0ODw",
        )
    with pytest.raises(DemoTokenIssueError) as key_error:
        _ = DemoTokenCodec(DemoTokenKey(b"short"), "epoch-0001")
    assert key_error.value.code is DemoTokenIssueErrorCode.KEY
    codec = DemoTokenCodec(SECRET, "epoch-0001")
    with pytest.raises(DemoTokenIssueError) as nonce_error:
        _ = codec.issue(DemoTokenIssue("session-0001", NOW, b"short"))
    assert nonce_error.value.code is DemoTokenIssueErrorCode.NONCE
    with pytest.raises(DemoTokenIssueError) as time_error:
        _ = codec.issue(DemoTokenIssue("session-0001", NOW.replace(tzinfo=None), b"\0" * 16))
    assert time_error.value.code is DemoTokenIssueErrorCode.TIME
    assert str(time_error.value) == DemoTokenIssueErrorCode.TIME.value
    assert "demo-token-test-key" not in repr(codec)


def test_demo_token_rejects_valid_hmac_for_invalid_or_noncanonical_payload() -> None:
    # Given: authenticated bytes that are invalid JSON and noncanonical valid claims.
    key = bytes(SECRET)
    codec = DemoTokenCodec(SECRET, "epoch-0001")
    invalid_json = _signed_token(b"{}", key)
    claims = DemoTokenClaims(
        v=1,
        session_id="session-0001",
        startup_epoch="epoch-0001",
        issued_at="2026-08-27T00:00:00Z",
        expires_at="2026-08-27T00:15:00Z",
        nonce="AAECAwQFBgcICQoLDA0ODw",
    )
    noncanonical_payload = json.dumps(claims.model_dump(mode="json"), indent=1).encode()
    noncanonical = _signed_token(noncanonical_payload, key)
    # When: both HMAC-valid tokens are validated.
    invalid_result = codec.validate(invalid_json, NOW)
    noncanonical_result = codec.validate(noncanonical, NOW)
    # Then: authentication alone cannot bypass the canonical typed boundary.
    assert invalid_result == DemoTokenRejected(DemoTokenFailureCode.INVALID)
    assert noncanonical_result == DemoTokenRejected(DemoTokenFailureCode.INVALID)


def test_demo_token_rejects_naive_validation_time() -> None:
    # Given: one valid current-epoch token.
    codec = DemoTokenCodec(SECRET, "epoch-0001")
    token, _ = codec.issue(DemoTokenIssue("session-0001", NOW, b"\x08" * 16))
    # When: validation receives a timezone-naive instant.
    result = codec.validate(token, NOW.replace(tzinfo=None))
    # Then: ambiguous wall-clock interpretation fails closed.
    assert result == DemoTokenRejected(DemoTokenFailureCode.INVALID)


@pytest.mark.parametrize("malformed", ["=.", "A.A", "AB.AQ"])
def test_demo_token_rejects_noncanonical_base64_components(malformed: str) -> None:
    # Given: malformed, exception-shaped, or noncanonical base64url components.
    codec = DemoTokenCodec(SECRET, "epoch-0001")
    # When: the token parser authenticates the components.
    result = codec.validate(malformed, NOW)
    # Then: every form maps to the same 401-domain invalid result.
    assert result == DemoTokenRejected(DemoTokenFailureCode.INVALID)


def test_store_rejects_duplicate_session_and_append_to_unknown_session() -> None:
    async def scenario() -> None:
        # Given: one live session.
        store = DemoSessionStore(signing_key=SECRET, startup_epoch="epoch-0001")
        request = SessionCreate(session_id="session-0001", now=NOW, nonce=b"\x07" * 16)
        created = await store.create_session(request)
        assert not isinstance(created, SessionCreateDenied)
        # When: the ID is recreated and an event targets an absent session.
        duplicate = await store.create_session(request)
        unknown = await store.append_event(
            AppendEventRequest(
                session_id="session-absent",
                idempotency_key="idem-absent",
                body_hash="a" * 64,
                event=store_event(1),
            )
        )
        # Then: no live state is overwritten or implicitly created.
        assert isinstance(duplicate, SessionCreateDenied)
        assert duplicate.code is SessionAccessCode.SESSION_EXISTS
        assert isinstance(unknown, EventAppendDenied)
        assert unknown.code is SessionAccessCode.NOT_FOUND

    anyio.run(scenario)
