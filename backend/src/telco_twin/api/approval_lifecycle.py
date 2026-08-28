"""Policy-bound approval-request and signed evidence decision lifecycle."""

from __future__ import annotations

import secrets
from dataclasses import replace
from typing import TYPE_CHECKING, final

from telco_twin.api.approval_window import require_open_approval_window
from telco_twin.api.contracts import (
    ApprovalDecisionResponse,
    ApprovalReadResponse,
    ApprovalRequestResponse,
    EmptyRequest,
)
from telco_twin.api.errors import ProblemError
from telco_twin.api.mutations import EvidenceAppend, append_mutation, stable_id
from telco_twin.api.runtime_models import ApprovalResource
from telco_twin.approval.authority import (
    ApprovalProofIssue,
    ApprovalRequestIssue,
    issue_approval_request,
)
from telco_twin.approval.state_machine import ApprovalEvidenceState
from telco_twin.domain.approval import ApprovalDecision
from telco_twin.safety.local_policy import LocalPolicyInput, evaluate_local_policy
from telco_twin.simulator.metrics import QualityPolicy

if TYPE_CHECKING:
    from telco_twin.api.runtime import ApiRuntime, AuthorizedSession


@final
class ApprovalLifecycle:
    """Own pending admission and evidence-only terminal decisions."""

    def __init__(self, runtime: ApiRuntime) -> None:
        """Bind the lifecycle to one process runtime."""
        self._runtime = runtime

    async def create_request(
        self,
        authorized: AuthorizedSession,
        simulation_id: str,
        idempotency_key: str,
        body: EmptyRequest,
    ) -> tuple[ApprovalRequestResponse, bool]:
        """Evaluate policy and create one pending approval evidence request."""
        session = authorized.session
        request_id = stable_id("approval-request", session.session_id, idempotency_key)
        evidence_id = stable_id("evidence", session.session_id, idempotency_key)
        async with session.lock:
            simulation = session.simulations.get(simulation_id)
            if simulation is None:
                raise ProblemError(
                    404,
                    "simulation_not_found",
                    "Simulation not found",
                    "The simulation does not exist in this live session.",
                )
            run = session.runs[simulation.run_id]
            if run.comparison_id is None:
                raise ProblemError(
                    409,
                    "comparison_required",
                    "Comparison required",
                    "A completed comparison is required before approval.",
                )
            comparison = session.comparisons[run.comparison_id]
            scenario = session.scenarios[run.scenario_id]
            policy = evaluate_local_policy(
                LocalPolicyInput(
                    observation=scenario.observation,
                    quality_policy=QualityPolicy(),
                    run=simulation.run,
                    comparison=comparison.comparison,
                ),
                self._runtime.clock,
            )
            if not policy.evidence.eligible:
                raise ProblemError(
                    422,
                    "policy_ineligible",
                    "Policy ineligible",
                    "The local policy rejected the current evidence.",
                )
            mutation = await append_mutation(
                self._runtime,
                authorized,
                EvidenceAppend(
                    idempotency_key=idempotency_key,
                    event_type="approval-requested",
                    body=body,
                    scenario_id=run.scenario_id,
                    run_id=run.run_id,
                    resource_id=request_id,
                ),
            )
            if mutation.replayed:
                resource = session.approval_requests.get(request_id)
                if resource is None:
                    raise ProblemError(
                        503,
                        "session_state_unavailable",
                        "Session state unavailable",
                        "The replayed approval state is unavailable.",
                    )
                return self._response(resource), True
            evidence = policy.evidence
            if evidence.patch_hash is None or evidence.simulation_hash is None:
                raise ProblemError(
                    422,
                    "policy_provenance_required",
                    "Policy provenance required",
                    "The policy result lacks simulator provenance.",
                )
            requested_at = session.signer.certificate.issued_at
            request = issue_approval_request(
                ApprovalRequestIssue(
                    request_id=request_id,
                    session_id=session.session_id,
                    patch_hash=evidence.patch_hash,
                    simulation_hash=evidence.simulation_hash,
                    policy_hash=evidence.policy_hash,
                    requested_at=requested_at,
                    nonce=secrets.token_bytes(16),
                )
            )
            _ = await session.approvals.record_request(
                request,
                policy,
                session.signer.certificate,
            )
            resource = ApprovalResource(request, policy, run.run_id, evidence_id)
            session.approval_requests[request_id] = resource
            session.runs[run.run_id] = replace(run, approval_request_id=request_id)
            return self._response(resource), False

    @staticmethod
    def _response(resource: ApprovalResource) -> ApprovalRequestResponse:
        return ApprovalRequestResponse(
            approval_request=resource.request,
            policy=resource.policy.evidence,
            run_id=resource.run_id,
            evidence_id=resource.evidence_id,
        )

    async def get(
        self,
        authorized: AuthorizedSession,
        request_id: str,
    ) -> ApprovalReadResponse:
        """Read one caller-owned request and its current append-only state."""
        async with authorized.session.lock:
            resource = authorized.session.approval_requests.get(request_id)
            if resource is None:
                raise ProblemError(
                    404,
                    "approval_request_not_found",
                    "Approval request not found",
                    "The request does not exist in this live session.",
                )
            record = await authorized.session.approvals.get(request_id)
            if record is None:
                raise ProblemError(
                    503,
                    "approval_state_unavailable",
                    "Approval state unavailable",
                    "The approval evidence state is unavailable.",
                )
            return ApprovalReadResponse(
                approval_request=record.request,
                state=record.state,
                proof_hash=record.proof_hash,
            )

    async def decide_demo(
        self,
        authorized: AuthorizedSession,
        request_id: str,
        idempotency_key: str,
        body: EmptyRequest,
        decision: ApprovalDecision,
    ) -> tuple[ApprovalDecisionResponse, bool]:
        """Record one demo-holder decision through the Task 5 event/store seam."""
        session = authorized.session
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
            if resource.proof is not None and resource.proof.proof_id != proof_id:
                raise ProblemError(
                    409,
                    "approval_already_terminal",
                    "Approval already terminal",
                    "The request already has terminal evidence.",
                )
            if resource.proof is None:
                require_open_approval_window(resource, session.signer, self._runtime.clock)
            mutation = await append_mutation(
                self._runtime,
                authorized,
                EvidenceAppend(
                    idempotency_key=idempotency_key,
                    event_type=(
                        "approval-approved"
                        if decision is ApprovalDecision.APPROVED
                        else "approval-rejected"
                    ),
                    body=body,
                    scenario_id=session.runs[resource.run_id].scenario_id,
                    run_id=resource.run_id,
                    resource_id=proof_id,
                ),
            )
            if mutation.replayed:
                if resource.proof is None:
                    raise ProblemError(
                        503,
                        "approval_state_unavailable",
                        "Approval state unavailable",
                        "The replayed approval proof is unavailable.",
                    )
                state = (
                    ApprovalEvidenceState.APPROVED
                    if resource.proof.decision is ApprovalDecision.APPROVED
                    else ApprovalEvidenceState.REJECTED
                )
                return ApprovalDecisionResponse(
                    state=state, approval_proof=resource.proof, effect="evidence-only"
                ), True
            proof = session.signer.issue_proof(
                ApprovalProofIssue(
                    request=resource.request,
                    decision=decision,
                    proof_id=proof_id,
                    approved_at=resource.request.requested_at,
                )
            )
            record = await session.approvals.record_proof(proof)
            session.approval_requests[request_id] = replace(resource, proof=proof)
            return ApprovalDecisionResponse(
                state=record.state, approval_proof=proof, effect="evidence-only"
            ), False
