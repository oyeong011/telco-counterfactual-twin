import { patchInputMatches } from "./workflow-bindings"
import { storePatch, storeScenario } from "./workflow-storage"
import type {
  WorkflowAction,
  WorkflowState,
  WorkflowStorage,
  WorkflowTransition,
} from "./workflow-types"

function illegal(state: WorkflowState, action: WorkflowAction): WorkflowTransition {
  return {
    ok: false,
    error: { kind: "illegal_transition", phase: state.phase, action: action.type },
  }
}

export function bootstrapStarted(
  state: WorkflowState,
  action: Extract<WorkflowAction, { readonly type: "bootstrap_started" }>,
): WorkflowTransition {
  return state.phase === "no-session"
    ? { ok: true, state: { phase: "bootstrapping" } }
    : illegal(state, action)
}

export function bootstrapSucceeded(
  state: WorkflowState,
  action: Extract<WorkflowAction, { readonly type: "bootstrap_succeeded" }>,
  storage: WorkflowStorage,
): WorkflowTransition {
  if (state.phase !== "bootstrapping") return illegal(state, action)
  return {
    ok: true,
    state: {
      phase: "session-active",
      session: action.session,
      drafts: storage.listRunDrafts(action.session.session_id),
    },
  }
}

export function scenarioCreated(
  state: WorkflowState,
  action: Extract<WorkflowAction, { readonly type: "scenario_created" }>,
  storage: WorkflowStorage,
): WorkflowTransition {
  if (state.phase !== "session-active") return illegal(state, action)
  return {
    ok: true,
    state: {
      phase: "scenario",
      session: state.session,
      run: storeScenario(storage, action.response, state.session.session_id),
      scenario: action.response,
    },
  }
}

export function diagnosisRecorded(
  state: WorkflowState,
  action: Extract<WorkflowAction, { readonly type: "diagnosis_recorded" }>,
): WorkflowTransition {
  if (state.phase !== "scenario") return illegal(state, action)
  if (
    action.response.scenario_id !== state.scenario.scenario.scenario_id ||
    action.response.run_id !== state.run.runId
  )
    return illegal(state, action)
  return {
    ok: true,
    state: {
      phase: "diagnosis",
      session: state.session,
      run: state.run,
      scenario: state.scenario,
      diagnosis: action.response,
    },
  }
}

export function patchProposed(
  state: WorkflowState,
  action: Extract<WorkflowAction, { readonly type: "patch_proposed" }>,
  storage: WorkflowStorage,
): WorkflowTransition {
  if (state.phase !== "diagnosis") return illegal(state, action)
  if (
    action.response.patch.scenario_id !== state.run.scenarioId ||
    action.response.run_id !== state.run.runId ||
    action.response.patch.base_topology_hash !== state.scenario.topology_hash ||
    !patchInputMatches(action.submittedPatch, action.response)
  )
    return illegal(state, action)
  return {
    ok: true,
    state: {
      phase: "patch",
      session: state.session,
      run: storePatch(storage, state, action.response, action.submittedPatch),
      scenario: state.scenario,
      diagnosis: state.diagnosis,
      patch: action.response,
    },
  }
}
