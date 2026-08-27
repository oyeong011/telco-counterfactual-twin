"""Deterministic local approval chains and application-owned state fixtures."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from telco_twin.approval.authority import (
    ApprovalProofIssue,
    ApprovalRequestIssue,
    AuthorityMode,
    SessionIssue,
    issue_approval_request,
    load_approval_authority,
)
from telco_twin.approval.state_machine import ApprovalStateMachine
from telco_twin.approval.trust import ApprovalTrustConfig
from telco_twin.domain.approval import (
    ApprovalDecision,
    ApprovalProof,
    ApprovalRequest,
    ApprovalValidationContext,
    Environment,
)
from telco_twin.state.trusted_clock import FixedClock, TrustedClock

if TYPE_CHECKING:
    from telco_twin.safety.local_policy import PolicyDecision

from .test_local_policy import real_policy_decision


class MutableClock:
    """Test-owned clock whose explicit advance models trusted elapsed time."""

    def __init__(self, current: datetime) -> None:
        self.current: datetime = current

    def now(self) -> datetime:
        return self.current

    def advance_to(self, current: datetime) -> None:
        self.current = current


def approval_chain() -> tuple[
    PolicyDecision,
    ApprovalRequest,
    ApprovalProof,
    ApprovalValidationContext,
]:
    """Return one valid local approved chain and its low-level context."""
    authority = load_approval_authority(AuthorityMode.LOCAL)
    session = authority.issue_session(
        SessionIssue(session_id="session-0001", issued_at="2026-08-27T00:00:00Z")
    )
    policy = real_policy_decision()
    evidence = policy.evidence
    assert evidence.patch_hash is not None
    assert evidence.simulation_hash is not None
    request = issue_approval_request(
        ApprovalRequestIssue(
            request_id="approval-request-0001",
            session_id="session-0001",
            patch_hash=evidence.patch_hash,
            simulation_hash=evidence.simulation_hash,
            policy_hash=evidence.policy_hash,
            requested_at="2026-08-27T00:00:00Z",
            nonce=b"\x01" * 16,
        )
    )
    proof = session.issue_proof(
        ApprovalProofIssue(
            request=request,
            decision=ApprovalDecision.APPROVED,
            proof_id="approval-proof-0001",
            approved_at="2026-08-27T00:00:00Z",
        )
    )
    context = ApprovalValidationContext(
        root=authority.descriptor,
        certificate=session.certificate,
        request=request,
        environment=Environment.TEST,
        trusted_root_hashes=frozenset({authority.descriptor.descriptor_hash}),
        consumed_nonces=frozenset(),
        now=datetime(2026, 8, 27, 0, 0, 30, tzinfo=UTC),
    )
    return policy, request, proof, context


def rejected_chain() -> tuple[
    PolicyDecision,
    ApprovalRequest,
    ApprovalProof,
    ApprovalValidationContext,
]:
    """Return the same valid local chain with a signed rejection decision."""
    policy, request, _, context = approval_chain()
    authority = load_approval_authority(AuthorityMode.LOCAL)
    session = authority.issue_session(
        SessionIssue(session_id=request.session_id, issued_at=request.requested_at)
    )
    proof = session.issue_proof(
        ApprovalProofIssue(
            request=request,
            decision=ApprovalDecision.REJECTED,
            proof_id="approval-proof-0002",
            approved_at=request.requested_at,
        )
    )
    return policy, request, proof, replace(context, certificate=session.certificate)


def machine_for(
    context: ApprovalValidationContext,
    clock: TrustedClock | None = None,
) -> ApprovalStateMachine:
    """Construct state from immutable application trust, never request context."""
    trust = ApprovalTrustConfig(
        environment=context.environment,
        root=context.root,
        trusted_root_hashes=context.trusted_root_hashes,
    )
    return ApprovalStateMachine(trust, clock or FixedClock(context.now))
