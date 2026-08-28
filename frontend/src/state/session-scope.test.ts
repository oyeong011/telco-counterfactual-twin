import { describe, expect, it } from "vitest"
import { ContractIdSchema, DemoSessionResponseSchema } from "../contracts/generated"
import {
  createSessionStorageAdapter,
  RUN_DRAFTS_STORAGE_KEY,
  type SessionStorageLike,
} from "./session"
import { createWorkflowStore } from "./workflow"
import { FakeStorage, patch, scenario, session } from "./workflow-fixtures"

const sessionB = DemoSessionResponseSchema.parse({
  ...session,
  session_id: "session-002",
  demo_token: "demo-token-secret-b",
  startup_epoch: "epoch-002",
  session_certificate: {
    ...session.session_certificate,
    session_id: "session-002",
  },
})

describe("session-scoped workflow storage", () => {
  it("does not expose session A drafts to session B", () => {
    // Given: two tab adapters sharing one sessionStorage backend.
    const backing = new FakeStorage()
    const adapterA = createSessionStorageAdapter(backing, session.session_id)
    const adapterB = createSessionStorageAdapter(backing, sessionB.session_id)
    adapterA.saveRunDraft({
      sessionId: session.session_id,
      runId: scenario.run_id,
      scenarioId: scenario.scenario.scenario_id,
      patchId: patch.patch.patch_id,
      patchBody: patch.patch,
    })

    // When: session B lists and saves its own run history.
    const beforeB = adapterB.listRunDrafts()
    adapterB.saveRunDraft({
      sessionId: sessionB.session_id,
      runId: ContractIdSchema.parse("run-002"),
      scenarioId: ContractIdSchema.parse("scenario-002"),
    })

    // Then: each session sees only its own IDs and patch body.
    expect(beforeB).toEqual([])
    expect(adapterB.listRunDrafts().map((draft) => draft.runId)).toEqual(["run-002"])
    expect(adapterA.listRunDrafts().map((draft) => draft.runId)).toEqual(["run-001"])
    expect(adapterB.listRunDrafts()[0]?.patchBody).toBeUndefined()
  })

  it("does not hydrate session B workflow history from session A", () => {
    // Given: session A has created a real scenario in shared tab storage.
    const backing = new FakeStorage()
    const adapterA = createSessionStorageAdapter(backing, session.session_id)
    const storeA = createWorkflowStore({ storage: adapterA })
    storeA.dispatch({ type: "bootstrap_started" })
    storeA.dispatch({ type: "bootstrap_succeeded", session })
    storeA.dispatch({ type: "scenario_created", response: scenario })

    // When: session B starts with the same tab storage.
    const storeB = createWorkflowStore({
      storage: createSessionStorageAdapter(backing, sessionB.session_id),
    })
    storeB.dispatch({ type: "bootstrap_started" })
    storeB.dispatch({ type: "bootstrap_succeeded", session: sessionB })

    // Then: B's restored history is empty and contains no A identifiers.
    const state = storeB.getState()
    expect(state.phase).toBe("session-active")
    if (state.phase === "session-active") expect(state.drafts).toEqual([])
  })

  it("rejects and removes the old unscoped storage format", () => {
    // Given: a pre-repair global array without a session binding.
    const backing: SessionStorageLike = new FakeStorage()
    backing.setItem(
      RUN_DRAFTS_STORAGE_KEY,
      JSON.stringify([{ runId: "run-001", scenarioId: "scenario-001" }]),
    )

    // When: a session-scoped adapter initializes.
    const drafts = createSessionStorageAdapter(backing, session.session_id).listRunDrafts()

    // Then: no unscoped data is exposed and the legacy value is cleared safely.
    expect(drafts).toEqual([])
    expect(backing.getItem(RUN_DRAFTS_STORAGE_KEY)).toBeNull()
  })

  it("does not let session A reset session B drafts", () => {
    // Given: two scoped adapters and one run owned by session B.
    const backing = new FakeStorage()
    const adapterA = createSessionStorageAdapter(backing, session.session_id)
    const adapterB = createSessionStorageAdapter(backing, sessionB.session_id)
    adapterB.saveRunDraft({
      sessionId: sessionB.session_id,
      runId: ContractIdSchema.parse("run-002"),
      scenarioId: ContractIdSchema.parse("scenario-002"),
    })

    // When: adapter A names B as the reset target.
    adapterA.resetRunDrafts(sessionB.session_id)

    // Then: B's run remains accessible only to B.
    expect(adapterB.listRunDrafts().map((draft) => draft.runId)).toEqual(["run-002"])
  })
})
