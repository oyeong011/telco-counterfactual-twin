import { canonicalJson, canonicalSha256 } from "../contracts/canonical-json"
import {
  type ApprovalDecisionResponse,
  type ApprovalRequestResponse,
  type ComparisonResponse,
  ContractIdSchema,
  type EvidenceResponse,
  type PatchResponse,
  Sha256HexSchema,
  type TypedPatch,
} from "../contracts/generated"
import type {
  ApprovalPendingState,
  ComparisonState,
  DecisionState,
  SimulationState,
} from "./workflow-types"

export function patchInputMatches(submittedPatch: TypedPatch, response: PatchResponse): boolean {
  const normalizedInput = { ...submittedPatch, extensions: submittedPatch.extensions ?? null }
  const normalizedResponse = {
    ...response.patch,
    extensions: response.patch.extensions ?? null,
  }
  return canonicalJson(normalizedInput) === canonicalJson(normalizedResponse)
}

export function comparisonBindsToState(
  state: SimulationState,
  response: ComparisonResponse,
): boolean {
  const result = response.comparison.result
  const hashes = response.comparison.evidence_hashes
  return (
    response.run_id === state.run.runId &&
    result.simulation_id === state.simulation.simulation_id &&
    result.scenario_id === state.scenario.scenario.scenario_id &&
    result.patch_hash === state.patch.patch_hash &&
    result.trace_hash === state.simulation.trace_hash &&
    result.candidate_hash === state.simulation.trace_hash &&
    hashes.patch_hash === state.patch.patch_hash &&
    result.baseline_hash === hashes.baseline_trace_hash &&
    result.candidate_hash === hashes.candidate_trace_hash &&
    hashes.candidate_trace_hash === state.simulation.trace_hash
  )
}

function comparisonHash(response: ComparisonResponse): string {
  const result = response.comparison.result
  const normalizedResult =
    result.extensions === null
      ? Object.fromEntries(Object.entries(result).filter(([key]) => key !== "extensions"))
      : result
  return canonicalSha256({ ...response.comparison, result: normalizedResult })
}

export function approvalRequestBindsToState(
  state: ComparisonState,
  response: ApprovalRequestResponse,
): boolean {
  const request = response.approval_request
  const policy = response.policy
  return (
    response.run_id === state.run.runId &&
    request.session_id === state.session.session_id &&
    request.patch_hash === state.patch.patch_hash &&
    request.patch_hash === state.comparison.comparison.result.patch_hash &&
    policy.patch_hash === state.patch.patch_hash &&
    policy.simulation_hash !== null &&
    request.simulation_hash === policy.simulation_hash &&
    request.simulation_hash === comparisonHash(state.comparison) &&
    request.policy_hash === policy.policy_hash &&
    request.requested_at === state.session.session_certificate.issued_at &&
    request.expires_at === state.session.session_certificate.expires_at &&
    state.comparison.comparison.result.approval_eligible
  )
}

export function approvalDecisionBindsToState(
  state: ApprovalPendingState,
  response: ApprovalDecisionResponse,
): boolean {
  const proof = response.approval_proof
  const request = state.approval.approval_request
  return (
    response.state !== "pending" &&
    response.state === proof.decision &&
    proof.approval_request_id === request.request_id &&
    proof.session_id === state.session.session_id &&
    proof.session_key_id === state.session.session_certificate.session_key_id &&
    proof.patch_hash === request.patch_hash &&
    proof.simulation_hash === request.simulation_hash &&
    proof.policy_hash === request.policy_hash &&
    proof.nonce === request.nonce &&
    proof.certificate_hash === canonicalSha256(state.session.session_certificate) &&
    proof.approved_at === request.requested_at &&
    proof.expires_at === request.expires_at
  )
}

function payloadString(event: EvidenceResponse["events"][number], key: string): string | null {
  const value = Object.entries(event.payload).find(([payloadKey]) => payloadKey === key)?.[1]
  return typeof value === "string" ? value : null
}

function decisionEventType(
  state: DecisionState["decision"]["state"],
): "approval-approved" | "approval-rejected" | null {
  switch (state) {
    case "approved":
      return "approval-approved"
    case "rejected":
      return "approval-rejected"
    case "pending":
      return null
  }
}

function eventChainBindsToState(state: DecisionState, response: EvidenceResponse): boolean {
  const decisionEvent = decisionEventType(state.decision.state)
  if (decisionEvent === null) return false
  const expected = [
    { eventType: "scenario-created", resourceId: state.scenario.scenario.scenario_id },
    { eventType: "scenario-diagnosed", resourceId: null },
    { eventType: "patch-proposed", resourceId: state.patch.patch.patch_id },
    { eventType: "simulation-completed", resourceId: state.simulation.simulation_id },
    { eventType: "comparison-created", resourceId: state.comparison.comparison_id },
    { eventType: "approval-requested", resourceId: state.approval.approval_request.request_id },
    { eventType: decisionEvent, resourceId: state.decision.approval_proof.proof_id },
  ] as const
  if (response.events.length !== expected.length) return false
  const eventIds = new Set<string>()
  let previousSequence = -1
  for (const [index, event] of response.events.entries()) {
    const expectedEvent = expected[index]
    if (expectedEvent === undefined) return false
    const resourceId = payloadString(event, "resource_id")
    if (
      event.event_type !== expectedEvent.eventType ||
      event.scenario_id !== state.scenario.scenario.scenario_id ||
      payloadString(event, "run_id") !== state.run.runId ||
      payloadString(event, "status") !== "recorded" ||
      !Sha256HexSchema.safeParse(payloadString(event, "request_hash")).success ||
      eventIds.has(event.event_id) ||
      event.sequence_id <= previousSequence
    )
      return false
    if (
      expectedEvent.resourceId === null
        ? !ContractIdSchema.safeParse(resourceId).success
        : resourceId !== expectedEvent.resourceId
    )
      return false
    eventIds.add(event.event_id)
    previousSequence = event.sequence_id
  }
  return true
}

export function evidenceBindsToState(state: DecisionState, response: EvidenceResponse): boolean {
  const card = response.evidence_card
  const proof = response.approval_proof
  const request = state.approval.approval_request
  const decision = state.decision.approval_proof
  return (
    response.run_id === state.run.runId &&
    card.evidence_id === state.approval.evidence_id &&
    card.session_id === state.session.session_id &&
    card.scenario_hash === state.scenario.scenario_hash &&
    card.patch_hash === state.patch.patch_hash &&
    card.simulation_hash === request.simulation_hash &&
    card.policy_hash === request.policy_hash &&
    card.seed === state.scenario.scenario.seed &&
    proof !== null &&
    card.approval_proof_hash === canonicalSha256(proof) &&
    canonicalJson(proof) === canonicalJson(decision) &&
    eventChainBindsToState(state, response)
  )
}
