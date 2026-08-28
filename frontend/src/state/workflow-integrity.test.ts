import { describe, expect, it } from "vitest"
import {
  ApprovalDecisionResponseSchema,
  ApprovalRequestResponseSchema,
  EventSchema,
  EvidenceResponseSchema,
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

function pendingStore(): WorkflowStore {
  const store = createWorkflowStore()
  advance(store, [...THROUGH_COMPARISON, { type: "approval_requested", response: approval }])
  return store
}

type EventFixture = {
  readonly eventId: string
  readonly sequenceId: number
  readonly eventType: string
  readonly resourceId: string
}

function event(fixture: EventFixture) {
  return EventSchema.parse({
    schema_version: "1.0",
    event_id: fixture.eventId,
    scenario_id: "scenario-001",
    timestamp: `2026-08-28T00:00:0${fixture.sequenceId}Z`,
    priority: 0,
    sequence_id: fixture.sequenceId,
    event_type: fixture.eventType,
    payload: {
      request_hash: HASHES.constraint,
      resource_id: fixture.resourceId,
      run_id: "run-001",
      status: "recorded",
    },
  })
}

describe("workflow semantic integrity", () => {
  it("rejects matching forged request and policy simulation hashes", () => {
    // Given: a real comparison and a self-consistent policy for another comparison.
    const store = createWorkflowStore()
    advance(store, THROUGH_COMPARISON)
    const forgedSimulationHash = "0".repeat(64)
    const forgedPolicyHash = "0f897c245f4ff99030003b9f90f95a8a2936549330dc44150b26fcbc337a90d3"
    const forged = ApprovalRequestResponseSchema.parse({
      ...approval,
      approval_request: {
        ...approval.approval_request,
        simulation_hash: forgedSimulationHash,
        policy_hash: forgedPolicyHash,
      },
      policy: {
        ...approval.policy,
        simulation_hash: forgedSimulationHash,
        policy_hash: forgedPolicyHash,
      },
    })

    // When: the forged response attempts to become pending.
    const result = store.dispatch({ type: "approval_requested", response: forged })

    // Then: equality between two forged fields cannot replace comparison binding.
    expect(result.ok).toBe(false)
    expect(store.getState().phase).toBe("comparison")
  })

  it("rejects a proof with a certificate hash unrelated to the active session", () => {
    // Given: a pending approval and a proof carrying another certificate digest.
    const store = pendingStore()
    const forged = ApprovalDecisionResponseSchema.parse({
      ...decision,
      approval_proof: { ...decision.approval_proof, certificate_hash: "0".repeat(64) },
    })

    // When: the forged proof is dispatched.
    const result = store.dispatch({ type: "approval_decided", response: forged })

    // Then: pending remains the last truthful state.
    expect(result.ok).toBe(false)
    expect(store.getState().phase).toBe("approval-pending")
  })

  it("rejects a complete event set in the wrong lifecycle order", () => {
    // Given: an accepted proof and all expected events with diagnosis and patch swapped.
    const store = pendingStore()
    advance(store, [{ type: "approval_decided", response: decision }])
    const events = [
      event({
        eventId: "event-001",
        sequenceId: 0,
        eventType: "scenario-created",
        resourceId: "scenario-001",
      }),
      event({
        eventId: "event-002",
        sequenceId: 1,
        eventType: "patch-proposed",
        resourceId: "patch-001",
      }),
      event({
        eventId: "event-003",
        sequenceId: 2,
        eventType: "scenario-diagnosed",
        resourceId: "diagnosis-001",
      }),
      event({
        eventId: "event-004",
        sequenceId: 3,
        eventType: "simulation-completed",
        resourceId: "simulation-001",
      }),
      event({
        eventId: "event-005",
        sequenceId: 4,
        eventType: "comparison-created",
        resourceId: "comparison-001",
      }),
      event({
        eventId: "event-006",
        sequenceId: 5,
        eventType: "approval-requested",
        resourceId: "approval-request-001",
      }),
      event({
        eventId: "event-007",
        sequenceId: 6,
        eventType: "approval-approved",
        resourceId: "approval-proof-001",
      }),
    ]
    const evidence = EvidenceResponseSchema.parse({
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
      events,
      approval_proof: decision.approval_proof,
    })

    // When: the out-of-order evidence is loaded.
    const result = store.dispatch({ type: "evidence_loaded", response: evidence })

    // Then: monotonic sequence IDs do not excuse semantic reordering.
    expect(result.ok).toBe(false)
    expect(store.getState().phase).toBe("decision")
  })
})
