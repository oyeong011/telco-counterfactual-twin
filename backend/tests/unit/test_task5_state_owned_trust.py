"""State-owned approval trust-root regressions."""

from datetime import UTC, datetime

import anyio
import pytest
from nacl.signing import SigningKey

from telco_twin.approval.authority import (
    ApprovalProofIssue,
    AuthorityLoadError,
    AuthorityLoadErrorCode,
    AuthorityMode,
    RootApprovalAuthority,
    SessionIssue,
    load_approval_authority,
)
from telco_twin.domain.approval import (
    ApprovalDecision,
    ApprovalValidationContext,
    ContractViolationError,
    Environment,
    encode_base64url,
    validate_approval_chain,
)

from .approval_test_support import approval_chain, machine_for
from .test_approval_authority import production_descriptor


def test_caller_self_allowlisted_attacker_root_cannot_approve_pending_request() -> None:
    async def scenario() -> None:
        # Given: legitimate pending evidence and an attacker-owned root/session chain.
        policy, request, _, context = approval_chain()
        attacker_key = SigningKey(b"\x75" * 32)
        attacker_root = production_descriptor(attacker_key)
        attacker = RootApprovalAuthority(attacker_root, attacker_key)
        attacker_session = attacker.issue_session(
            SessionIssue(session_id=request.session_id, issued_at=request.requested_at)
        )
        attacker_proof = attacker_session.issue_proof(
            ApprovalProofIssue(
                request=request,
                decision=ApprovalDecision.APPROVED,
                proof_id="proof-attacker-root",
                approved_at=request.requested_at,
            )
        )
        attacker_context = ApprovalValidationContext(
            root=attacker.descriptor,
            certificate=attacker_session.certificate,
            request=request,
            environment=Environment.PRODUCTION,
            trusted_root_hashes=frozenset({attacker.descriptor.descriptor_hash}),
            consumed_nonces=frozenset(),
            now=datetime(2026, 8, 27, 0, 0, 30, tzinfo=UTC),
        )
        validate_approval_chain(attacker_proof, attacker_context)
        machine = machine_for(context)
        _ = await machine.record_request(request, policy, context.certificate)
        # When/Then: attacker proof cannot substitute root/certificate configuration.
        with pytest.raises(ContractViolationError):
            _ = await machine.record_proof(attacker_proof)

    anyio.run(scenario)


def test_production_authority_requires_independent_trusted_root_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: matching production signing material but no independent trusted-root config.
    key = SigningKey(b"\x76" * 32)
    descriptor = production_descriptor(key)
    monkeypatch.setenv("APPROVAL_ROOT_KEY_SECRET", encode_base64url(bytes(key)))
    monkeypatch.delenv("APPROVAL_TRUSTED_ROOT_HASHES_JSON", raising=False)
    # When: production authority startup is attempted.
    with pytest.raises(AuthorityLoadError) as caught:
        _ = load_approval_authority(AuthorityMode.PRODUCTION, descriptor)
    # Then: a descriptor cannot self-authorize.
    assert caught.value.code is AuthorityLoadErrorCode.ROOT_UNTRUSTED


@pytest.mark.parametrize("configured", ["not-json", "[]"])
def test_production_authority_rejects_invalid_or_empty_trusted_root_set(
    monkeypatch: pytest.MonkeyPatch,
    configured: str,
) -> None:
    key = SigningKey(b"\x77" * 32)
    descriptor = production_descriptor(key)
    monkeypatch.setenv("APPROVAL_ROOT_KEY_SECRET", encode_base64url(bytes(key)))
    monkeypatch.setenv("APPROVAL_TRUSTED_ROOT_HASHES_JSON", configured)
    with pytest.raises(AuthorityLoadError) as caught:
        _ = load_approval_authority(AuthorityMode.PRODUCTION, descriptor)
    assert caught.value.code is AuthorityLoadErrorCode.ROOT_UNTRUSTED
