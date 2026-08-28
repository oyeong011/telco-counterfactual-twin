import { describe, expect, it } from "vitest"
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
      { type: "patch_proposed" as const, response: patch },
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
    const result = store.dispatch({ type: "patch_proposed", response: patch })

    // Then: the transition is typed as a failure and state is unchanged.
    expect(result.ok).toBe(false)
    expect(store.getState()).toBe(before)
  })

  it("persists intermediate IDs and patch body without the session token", () => {
    // Given: a tab-scoped storage adapter and a workflow through patch proposal.
    const backing = new FakeStorage()
    const storage = createSessionStorageAdapter(backing)
    const store = createWorkflowStore({ storage })
    store.dispatch({ type: "bootstrap_started" })
    store.dispatch({ type: "bootstrap_succeeded", session })
    store.dispatch({ type: "scenario_created", response: scenario })
    store.dispatch({ type: "diagnosis_recorded", response: diagnosis })
    store.dispatch({ type: "patch_proposed", response: patch })
    store.dispatch({ type: "simulation_completed", response: simulation })

    // When: a fresh adapter restores the tab's run draft.
    const restored = createSessionStorageAdapter(backing).listRunDrafts()

    // Then: IDs and the submitted patch are recoverable, while bearer material is absent.
    expect(restored).toHaveLength(1)
    expect(restored[0]?.simulationId).toBe("simulation-001")
    expect(restored[0]?.patchBody?.patch_id).toBe("patch-001")
    expect(backing.getItem("telco-twin:run-drafts")).not.toContain(session.demo_token)
  })
})
