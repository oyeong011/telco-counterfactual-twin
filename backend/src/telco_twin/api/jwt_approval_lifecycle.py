"""JWT-authorized evidence decision path without persisting demo bearers."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, final

from telco_twin.api.approval_window import require_open_approval_window
from telco_twin.api.contracts import ApprovalDecisionResponse, EmptyRequest
from telco_twin.api.errors import ProblemError
from telco_twin.api.mutations import (
    EvidenceAppend,
    idempotency_claim,
    prior_idempotency,
    record_idempotency,
    stable_id,
)
from telco_twin.approval.authority import ApprovalProofIssue
from telco_twin.approval.state_machine import ApprovalEvidenceState
from telco_twin.domain.approval import ApprovalDecision
from telco_twin.domain.event import Event
from telco_twin.simulator.frozen_event import snapshot_event
from telco_twin.state.limits import MAX_EVENTS_PER_SESSION
from telco_twin.state.trusted_clock import trusted_timestamp

if TYPE_CHECKING:
    from telco_twin.api.runtime import ApiRuntime
    from telco_twin.api.runtime_models import ApiSession


@final
class JwtApprovalLifecycle:
    """Record configured JWT decisions while retaining no demo token."""

    def __init__(self, runtime: ApiRuntime) -> None:
        """Bind JWT decisions to one process runtime."""
        self._runtime = runtime

    async def decide(
        self,
        session: ApiSession,
        request_id: str,
        idempotency_key: str,
        body: EmptyRequest,
        decision: ApprovalDecision,
    ) -> tuple[ApprovalDecisionResponse, bool]:
        """Record one independently authenticated terminal proof and audit event."""
        async with session.lock:
            resource = session.approval_requests.get(request_id)
            if resource is None:
                raise ProblemError(
                    404,
                    "approval_request_not_found",
                    "Approval request not found",
                    "The request does not exist in this live session.",
                )
            proof_id = stable_id("approval-proof", session.session_id, idempotency_key)
            event_type = (
                "approval-approved"
                if decision is ApprovalDecision.APPROVED
                else "approval-rejected"
            )
            append = EvidenceAppend(
                idempotency_key=idempotency_key,
                event_type=event_type,
                body=body,
                scenario_id=session.runs[resource.run_id].scenario_id,
                run_id=resource.run_id,
                resource_id=proof_id,
            )
            claim = idempotency_claim(session.session_id, append)
            prior = prior_idempotency(session, claim)
            if resource.proof is not None:
                if resource.proof.proof_id != proof_id or resource.proof.decision is not decision:
                    raise ProblemError(
                        409,
                        "approval_already_terminal",
                        "Approval already terminal",
                        "The request already has terminal evidence.",
                    )
                if prior is None:
                    raise ProblemError(
                        503,
                        "approval_state_unavailable",
                        "Approval state unavailable",
                        "The approval idempotency evidence is unavailable.",
                    )
                state = (
                    ApprovalEvidenceState.APPROVED
                    if decision is ApprovalDecision.APPROVED
                    else ApprovalEvidenceState.REJECTED
                )
                return ApprovalDecisionResponse(
                    state=state, approval_proof=resource.proof, effect="evidence-only"
                ), True
            if prior is not None:
                raise ProblemError(
                    503,
                    "approval_state_unavailable",
                    "Approval state unavailable",
                    "The approval proof is unavailable for the recorded idempotency result.",
                )
            require_open_approval_window(resource, session.signer, self._runtime.clock)
            if session.next_event_sequence >= MAX_EVENTS_PER_SESSION:
                raise ProblemError(
                    429,
                    "demo_event_capacity",
                    "Evidence capacity reached",
                    "The bounded append-only evidence capacity is full.",
                )
            proof = session.signer.issue_proof(
                ApprovalProofIssue(
                    request=resource.request,
                    decision=decision,
                    proof_id=proof_id,
                    approved_at=resource.request.requested_at,
                )
            )
            record = await session.approvals.record_proof(proof)
            run = session.runs[resource.run_id]
            event = snapshot_event(
                Event(
                    event_id=claim.event_id,
                    scenario_id=run.scenario_id,
                    timestamp=trusted_timestamp(self._runtime.clock),
                    priority=0,
                    sequence_id=session.next_event_sequence,
                    event_type=event_type,
                    payload={
                        "request_hash": claim.request_hash,
                        "resource_id": proof_id,
                        "run_id": resource.run_id,
                        "status": "recorded",
                    },
                    schema_version="1.0",
                )
            )
            session.external_events.append(event)
            session.next_event_sequence += 1
            record_idempotency(session, claim, event)
            session.approval_requests[request_id] = replace(resource, proof=proof)
            return ApprovalDecisionResponse(
                state=record.state,
                approval_proof=proof,
                effect="evidence-only",
            ), False
