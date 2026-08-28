import { describe, expect, it } from "vitest"
import { PatchResponseSchema, TypedPatchSchema, UtcTimestampSchema } from "../contracts/generated"
import { createSessionStorageAdapter } from "./session"
import { createWorkflowStore, type WorkflowState } from "./workflow"
import {
  approval,
  comparison,
  diagnosis,
  FakeStorage,
  patch,
  scenario,
  session,
  simulation,
} from "./workflow-fixtures"

describe("closed workflow store", () => {
  it("accepts only the governed lifecycle in order", () => {
    // Given: a store at the start of a synthetic session.
    const store = createWorkflowStore()

    // When: each real response is dispatched through the lifecycle.
    const actions = [
      { type: "bootstrap_started" as const },
      { type: "bootstrap_succeeded" as const, session },
      { type: "scenario_created" as const, response: scenario },
      { type: "diagnosis_recorded" as const, response: diagnosis },
      { type: "patch_proposed" as const, response: patch, submittedPatch: patch.patch },
      { type: "simulation_completed" as const, response: simulation },
      { type: "comparison_created" as const, response: comparison },
      { type: "approval_requested" as const, response: approval },
    ]
    for (const action of actions) expect(store.dispatch(action).ok).toBe(true)

    // Then: the state stops at an honest pending approval phase.
    expect(store.getState().phase).toBe("approval-pending")
  })

  it("rejects an illegal transition without changing state", () => {
    // Given: a new store that has no session or scenario.
    const store = createWorkflowStore()
    const before: WorkflowState = store.getState()

    // When: a patch response attempts to skip the governed lifecycle.
    const result = store.dispatch({
      type: "patch_proposed",
      response: patch,
      submittedPatch: patch.patch,
    })

    // Then: the transition is typed as a failure and state is unchanged.
    expect(result.ok).toBe(false)
    expect(store.getState()).toBe(before)
  })

  it("persists intermediate IDs and patch body without the session token", () => {
    // Given: a tab-scoped storage adapter and a workflow through patch proposal.
    const backing = new FakeStorage()
    const storage = createSessionStorageAdapter(backing, session.session_id)
    const store = createWorkflowStore({ storage })
    store.dispatch({ type: "bootstrap_started" })
    store.dispatch({ type: "bootstrap_succeeded", session })
    store.dispatch({ type: "scenario_created", response: scenario })
    store.dispatch({ type: "diagnosis_recorded", response: diagnosis })
    store.dispatch({ type: "patch_proposed", response: patch, submittedPatch: patch.patch })
    store.dispatch({ type: "simulation_completed", response: simulation })

    // When: a fresh adapter restores the tab's run draft.
    const restored = createSessionStorageAdapter(backing, session.session_id).listRunDrafts()

    // Then: IDs and the submitted patch are recoverable, while bearer material is absent.
    expect(restored).toHaveLength(1)
    expect(restored[0]?.simulationId).toBe("simulation-001")
    expect(restored[0]?.patchBody?.patch_id).toBe("patch-001")
    expect(backing.getItem(`telco-twin:run-drafts:${session.session_id}`)).not.toContain(
      session.demo_token,
    )
  })

  it("rejects a patch response that does not match the submitted patch input", () => {
    // Given: a diagnosis and a submitted patch whose timestamp differs from the server response.
    const store = createWorkflowStore({
      storage: createSessionStorageAdapter(new FakeStorage(), session.session_id),
    })
    store.dispatch({ type: "bootstrap_started" })
    store.dispatch({ type: "bootstrap_succeeded", session })
    store.dispatch({ type: "scenario_created", response: scenario })
    store.dispatch({ type: "diagnosis_recorded", response: diagnosis })
    const submittedPatch = TypedPatchSchema.parse({
      ...patch.patch,
      proposed_at: UtcTimestampSchema.parse("2026-08-28T00:00:01Z"),
    })

    // When: the response is linked with the submitted body.
    const result = store.dispatch({
      type: "patch_proposed",
      response: patch,
      submittedPatch,
    })

    // Then: a response for a different input cannot advance the workflow.
    expect(result.ok).toBe(false)
    expect(store.getState().phase).toBe("diagnosis")
  })

  it("accepts the backend's explicit null for an omitted optional extension", () => {
    // Given: a valid request without extensions and the backend-normalized response.
    const store = createWorkflowStore()
    store.dispatch({ type: "bootstrap_started" })
    store.dispatch({ type: "bootstrap_succeeded", session })
    store.dispatch({ type: "scenario_created", response: scenario })
    store.dispatch({ type: "diagnosis_recorded", response: diagnosis })
    const normalizedResponse = PatchResponseSchema.parse({
      ...patch,
      patch: { ...patch.patch, extensions: null },
    })

    // When: the exact submitted request is linked to its normalized response.
    const result = store.dispatch({
      type: "patch_proposed",
      response: normalizedResponse,
      submittedPatch: patch.patch,
    })

    // Then: omission and the backend's explicit null are treated as one contract value.
    expect(result.ok).toBe(true)
    expect(store.getState().phase).toBe("patch")
  })

  it("keeps policy ineligibility as an explicit blocked state", () => {
    // Given: a store that has reached comparison.
    const store = createWorkflowStore()
    for (const action of [
      { type: "bootstrap_started" as const },
      { type: "bootstrap_succeeded" as const, session },
      { type: "scenario_created" as const, response: scenario },
      { type: "diagnosis_recorded" as const, response: diagnosis },
      { type: "patch_proposed" as const, response: patch, submittedPatch: patch.patch },
      { type: "simulation_completed" as const, response: simulation },
      { type: "comparison_created" as const, response: comparison },
    ])
      store.dispatch(action)

    // When: the backend reports its intentionally detail-poor policy rejection.
    const result = store.dispatch({
      type: "approval_blocked",
      problem: {
        ok: false,
        problem: {
          type: "https://telco-twin.invalid/problems/policy_ineligible",
          title: "Policy ineligible",
          status: 422,
          code: "policy_ineligible",
          detail: "The local policy rejected the current evidence.",
          request_id: "request-001",
        },
        requestId: "request-001",
      },
    })

    // Then: blocked cannot be mistaken for a pending or approved request.
    expect(result.ok).toBe(true)
    expect(store.getState().phase).toBe("approval-blocked")
  })
})
