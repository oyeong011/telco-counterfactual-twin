import { describe, expect, it } from "vitest"
import {
  ApprovalDecisionResponseSchema,
  EventSchema,
  EvidenceResponseSchema,
} from "../contracts/generated"
import { createWorkflowStore } from "./workflow"
import {
  approval,
  comparison,
  diagnosis,
  HASH,
  patch,
  scenario,
  session,
  simulation,
} from "./workflow-fixtures"
import { deriveTopologyGraph } from "./workflow-graph"

describe("workflow safety gaps and projections", () => {
  it("keeps policy ineligibility as a truthful blocked gap", () => {
    // Given: a store that has reached comparison.
    const store = createWorkflowStore()
    for (const action of [
      { type: "bootstrap_started" as const },
      { type: "bootstrap_succeeded" as const, session },
      { type: "scenario_created" as const, response: scenario },
      { type: "diagnosis_recorded" as const, response: diagnosis },
      { type: "patch_proposed" as const, response: patch },
      { type: "simulation_completed" as const, response: simulation },
      { type: "comparison_created" as const, response: comparison },
    ])
      store.dispatch(action)

    // When: the server says policy eligibility is unavailable.
    const result = store.dispatch({
      type: "approval_blocked" as const,
      problem: {
        ok: false as const,
        problem: {
          type: "https://telco-twin.invalid/problems/policy_ineligible",
          title: "Policy ineligible",
          status: 422,
          code: "policy_ineligible",
          detail: "safe detail",
          request_id: "request-001",
        },
        requestId: "request-001",
      },
    })

    // Then: blocked is explicit and cannot be mistaken for a pending/approved decision.
    expect(result.ok).toBe(true)
    expect(store.getState().phase).toBe("approval-blocked")
    const attempted = store.dispatch({ type: "approval_requested", response: approval })
    expect(attempted.ok).toBe(false)
  })

  it("derives graph identifiers only from parsed event data", () => {
    // Given: events with a real resource and one malformed identifier.
    const parsedEvents = [
      EventSchema.parse({
        schema_version: "1.0",
        event_id: "event-001",
        scenario_id: "scenario-001",
        timestamp: "2026-08-28T00:00:00Z",
        priority: 0,
        sequence_id: 0,
        event_type: "scenario-created",
        payload: { resource_id: "cell-0001", run_id: "run-001", status: "recorded" },
      }),
      EventSchema.parse({
        schema_version: "1.0",
        event_id: "event-002",
        scenario_id: "scenario-001",
        timestamp: "2026-08-28T00:00:01Z",
        priority: 0,
        sequence_id: 1,
        event_type: "scenario-diagnosed",
        payload: { resource_id: "not valid", run_id: "run-001", status: "recorded" },
      }),
    ]

    // When: the UI topology projection is derived.
    const graph = deriveTopologyGraph(parsedEvents)

    // Then: only server-provided identifiers appear, with no placeholder nodes or edges.
    expect(graph.nodes.map((node) => node.id)).toEqual(["scenario-001", "cell-0001"])
    expect(graph.edges).toEqual([])
  })

  it("moves terminal approval evidence to decision and evidence", () => {
    // Given: a pending approval state.
    const store = createWorkflowStore()
    for (const action of [
      { type: "bootstrap_started" as const },
      { type: "bootstrap_succeeded" as const, session },
      { type: "scenario_created" as const, response: scenario },
      { type: "diagnosis_recorded" as const, response: diagnosis },
      { type: "patch_proposed" as const, response: patch },
      { type: "simulation_completed" as const, response: simulation },
      { type: "comparison_created" as const, response: comparison },
      { type: "approval_requested" as const, response: approval },
    ])
      store.dispatch(action)
    const decision = ApprovalDecisionResponseSchema.parse({
      state: "approved",
      approval_proof: {
        proof_id: "approval-proof-001",
        approval_request_id: "approval-request-001",
        session_id: "session-001",
        session_key_id: "session-key-001",
        patch_hash: HASH,
        simulation_hash: HASH,
        policy_hash: HASH,
        nonce: "A".repeat(22),
        decision: "approved",
        approved_at: "2026-08-28T00:00:00Z",
        expires_at: "2026-08-28T00:01:00Z",
        certificate_hash: HASH,
        proof_signature: "A".repeat(86),
        schema_version: "1.0",
      },
      effect: "evidence-only",
    })

    // When: the terminal decision is recorded.
    const decided = store.dispatch({ type: "approval_decided", response: decision })

    // Then: the decision is visible before evidence is loaded.
    expect(decided.ok).toBe(true)
    expect(store.getState().phase).toBe("decision")

    // When: the run evidence export is loaded after the decision.
    const evidence = EvidenceResponseSchema.parse({
      run_id: "run-001",
      evidence_card: {
        schema_version: "1.0",
        evidence_id: "evidence-001",
        session_id: "session-001",
        scenario_hash: HASH,
        patch_hash: HASH,
        simulation_hash: HASH,
        policy_hash: HASH,
        approval_proof_hash: HASH,
        seed: 6701,
        source_commit_sha: "b".repeat(40),
        contract_hashes: { scenario: HASH },
        generated_at: "2026-08-28T00:00:00Z",
      },
      events: [],
      approval_proof: decision.approval_proof,
    })
    const loaded = store.dispatch({ type: "evidence_loaded", response: evidence })

    // Then: the final state records only the server evidence for this run.
    expect(loaded.ok).toBe(true)
    expect(store.getState().phase).toBe("evidence")
  })
})
