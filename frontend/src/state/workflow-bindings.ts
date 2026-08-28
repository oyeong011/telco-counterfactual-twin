import { canonicalJson } from "../contracts/canonical-json"
import type {
  ApprovalDecisionResponse,
  ApprovalRequestResponse,
  ComparisonResponse,
  EvidenceResponse,
  PatchResponse,
  TypedPatch,
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
    proof.approved_at === request.requested_at &&
    proof.expires_at === request.expires_at
  )
}

function payloadString(event: EvidenceResponse["events"][number], key: string): string | null {
  const value = Object.entries(event.payload).find(([payloadKey]) => payloadKey === key)?.[1]
  return typeof value === "string" ? value : null
}

function eventChainBindsToState(state: DecisionState, response: EvidenceResponse): boolean {
  const eventIds = new Set<string>()
  const observedTypes = new Set<string>()
  const expectedResources = new Map<string, string>([
    ["scenario-created", state.scenario.scenario.scenario_id],
    ["patch-proposed", state.patch.patch.patch_id],
    ["simulation-completed", state.simulation.simulation_id],
    ["comparison-created", state.comparison.comparison_id],
    ["approval-requested", state.approval.approval_request.request_id],
    [
      state.decision.state === "approved" ? "approval-approved" : "approval-rejected",
      state.decision.approval_proof.proof_id,
    ],
  ])
  let previousSequence = -1
  for (const event of response.events) {
    if (
      event.scenario_id !== state.scenario.scenario.scenario_id ||
      payloadString(event, "run_id") !== state.run.runId ||
      eventIds.has(event.event_id) ||
      event.sequence_id <= previousSequence
    )
      return false
    eventIds.add(event.event_id)
    observedTypes.add(event.event_type)
    const expectedResource = expectedResources.get(event.event_type)
    if (expectedResource !== undefined && payloadString(event, "resource_id") !== expectedResource)
      return false
    previousSequence = event.sequence_id
  }
  return (
    observedTypes.has("scenario-diagnosed") &&
    [...expectedResources.keys()].every((eventType) => observedTypes.has(eventType))
  )
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
    card.approval_proof_hash !== null &&
    proof !== null &&
    canonicalJson(proof) === canonicalJson(decision) &&
    eventChainBindsToState(state, response)
  )
}
