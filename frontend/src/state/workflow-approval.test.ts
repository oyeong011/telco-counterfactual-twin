import { describe, expect, it } from "vitest"
import {
  ApprovalDecisionResponseSchema,
  ApprovalProofSchema,
  ApprovalRequestResponseSchema,
  EventSchema,
  EvidenceResponseSchema,
  Sha256HexSchema,
} from "../contracts/generated"
import { createWorkflowStore, type WorkflowAction, type WorkflowStore } from "./workflow"
import {
  approval,
  comparison,
  diagnosis,
  HASHES,
  patch,
  scenario,
  session,
  simulation,
} from "./workflow-fixtures"

const THROUGH_COMPARISON = [
  { type: "bootstrap_started" },
  { type: "bootstrap_succeeded", session },
  { type: "scenario_created", response: scenario },
  { type: "diagnosis_recorded", response: diagnosis },
  { type: "patch_proposed", response: patch, submittedPatch: patch.patch },
  { type: "simulation_completed", response: simulation },
  { type: "comparison_created", response: comparison },
] as const satisfies readonly WorkflowAction[]

const decision = ApprovalDecisionResponseSchema.parse({
  state: "approved",
  approval_proof: {
    proof_id: "approval-proof-001",
    approval_request_id: "approval-request-001",
    session_id: "session-001",
    session_key_id: "session-key-001",
    patch_hash: HASHES.patch,
    simulation_hash: HASHES.simulation,
    policy_hash: HASHES.policy,
    nonce: "A".repeat(22),
    decision: "approved",
    approved_at: "2026-08-28T00:00:00Z",
    expires_at: "2026-08-28T00:01:00Z",
    certificate_hash: HASHES.certificate,
    proof_signature: "A".repeat(86),
    schema_version: "1.0",
  },
  effect: "evidence-only",
})

function advance(store: WorkflowStore, actions: readonly WorkflowAction[]): void {
  for (const action of actions) expect(store.dispatch(action).ok).toBe(true)
}

function comparisonStore(): WorkflowStore {
  const store = createWorkflowStore()
  advance(store, THROUGH_COMPARISON)
  return store
}

function pendingStore(): WorkflowStore {
  const store = comparisonStore()
  advance(store, [{ type: "approval_requested", response: approval }])
  return store
}

function lifecycleEvent(
  eventId: string,
  sequenceId: number,
  eventType: string,
  resourceId: string,
) {
  return EventSchema.parse({
    schema_version: "1.0",
    event_id: eventId,
    scenario_id: scenario.scenario.scenario_id,
    timestamp: `2026-08-28T00:00:0${sequenceId}Z`,
    priority: 0,
    sequence_id: sequenceId,
    event_type: eventType,
    payload: {
      request_hash: HASHES.constraint,
      resource_id: resourceId,
      run_id: scenario.run_id,
      status: "recorded",
    },
  })
}

const events = [
  lifecycleEvent("event-001", 0, "scenario-created", "scenario-001"),
  lifecycleEvent("event-002", 1, "scenario-diagnosed", "diagnosis-001"),
  lifecycleEvent("event-003", 2, "patch-proposed", "patch-001"),
  lifecycleEvent("event-004", 3, "simulation-completed", "simulation-001"),
  lifecycleEvent("event-005", 4, "comparison-created", "comparison-001"),
  lifecycleEvent("event-006", 5, "approval-requested", "approval-request-001"),
  lifecycleEvent("event-007", 6, "approval-approved", "approval-proof-001"),
]

function evidenceWithProof(proof: typeof decision.approval_proof, observedEvents = events) {
  return EvidenceResponseSchema.parse({
    run_id: "run-001",
    evidence_card: {
      schema_version: "1.0",
      evidence_id: "evidence-001",
      session_id: "session-001",
      scenario_hash: HASHES.scenario,
      patch_hash: HASHES.patch,
      simulation_hash: HASHES.simulation,
      policy_hash: HASHES.policy,
      approval_proof_hash: HASHES.approvalProof,
      seed: 6701,
      source_commit_sha: "b".repeat(40),
      contract_hashes: { scenario: HASHES.scenario },
      generated_at: "2026-08-28T00:00:06Z",
    },
    events: observedEvents,
    approval_proof: proof,
  })
}

describe("approval and evidence chain bindings", () => {
  it("accepts one fully linked terminal evidence chain", () => {
    // Given: a pending request linked to distinct patch, simulation, and policy hashes.
    const store = pendingStore()

    // When: its exact terminal proof and complete observed event chain arrive.
    const decided = store.dispatch({ type: "approval_decided", response: decision })
    const loaded = store.dispatch({
      type: "evidence_loaded",
      response: evidenceWithProof(decision.approval_proof),
    })

    // Then: the workflow reaches evidence without granting runtime authority.
    expect(decided.ok).toBe(true)
    expect(loaded.ok).toBe(true)
    expect(store.getState().phase).toBe("evidence")
  })

  it("rejects an approval request with a different patch hash", () => {
    // Given: a comparison and a request linked to another patch.
    const store = comparisonStore()
    const contradictory = {
      ...approval,
      approval_request: {
        ...approval.approval_request,
        patch_hash: Sha256HexSchema.parse("0".repeat(64)),
      },
    }

    // When: the request attempts to become pending.
    const result = store.dispatch({ type: "approval_requested", response: contradictory })

    // Then: the comparison remains the last truthful state.
    expect(result.ok).toBe(false)
    expect(store.getState().phase).toBe("comparison")
  })

  it("rejects an approval request outside the session certificate window", () => {
    // Given: a separately valid 60-second request shifted beyond the certificate.
    const store = comparisonStore()
    const shifted = ApprovalRequestResponseSchema.parse({
      ...approval,
      approval_request: {
        ...approval.approval_request,
        requested_at: "2026-08-28T00:00:01Z",
        expires_at: "2026-08-28T00:01:01Z",
      },
    })

    // When: the request attempts to become pending.
    const result = store.dispatch({ type: "approval_requested", response: shifted })

    // Then: certificate-bound state does not advance.
    expect(result.ok).toBe(false)
    expect(store.getState().phase).toBe("comparison")
  })

  it("rejects a terminal state that contradicts its proof decision", () => {
    // Given: a pending approval and a structurally valid contradictory response.
    const store = pendingStore()
    const contradictory = ApprovalDecisionResponseSchema.parse({ ...decision, state: "rejected" })

    // When: the response is dispatched.
    const result = store.dispatch({ type: "approval_decided", response: contradictory })

    // Then: pending remains the last truthful state.
    expect(result.ok).toBe(false)
    expect(store.getState().phase).toBe("approval-pending")
  })

  it("rejects a proof window different from the pending request", () => {
    // Given: a pending request and a separately valid shifted proof TTL.
    const store = pendingStore()
    const shifted = ApprovalDecisionResponseSchema.parse({
      ...decision,
      approval_proof: {
        ...decision.approval_proof,
        approved_at: "2026-08-28T00:00:01Z",
        expires_at: "2026-08-28T00:01:01Z",
      },
    })

    // When: the shifted proof is dispatched.
    const result = store.dispatch({ type: "approval_decided", response: shifted })

    // Then: it cannot become terminal truth.
    expect(result.ok).toBe(false)
    expect(store.getState().phase).toBe("approval-pending")
  })

  it("rejects evidence whose proof differs from the accepted decision", () => {
    // Given: an accepted decision and evidence carrying a changed signature.
    const store = pendingStore()
    advance(store, [{ type: "approval_decided", response: decision }])
    const changedProof = ApprovalProofSchema.parse({
      ...decision.approval_proof,
      proof_signature: `B${"A".repeat(85)}`,
    })

    // When: the contradictory evidence is loaded.
    const result = store.dispatch({
      type: "evidence_loaded",
      response: evidenceWithProof(changedProof),
    })

    // Then: decision remains the last truthful state.
    expect(result.ok).toBe(false)
    expect(store.getState().phase).toBe("decision")
  })

  it("rejects evidence missing the accepted terminal event", () => {
    // Given: an accepted decision and an event chain truncated before that proof.
    const store = pendingStore()
    advance(store, [{ type: "approval_decided", response: decision }])

    // When: the incomplete evidence chain is loaded.
    const result = store.dispatch({
      type: "evidence_loaded",
      response: evidenceWithProof(decision.approval_proof, events.slice(0, -1)),
    })

    // Then: decision remains the last truthful state.
    expect(result.ok).toBe(false)
    expect(store.getState().phase).toBe("decision")
  })
})
