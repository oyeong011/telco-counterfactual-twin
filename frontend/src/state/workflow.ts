import { createSessionStorageAdapter, type SessionStorageAdapter } from "./session"
import {
  bootstrapStarted,
  bootstrapSucceeded,
  diagnosisRecorded,
  patchProposed,
  scenarioCreated,
} from "./workflow-early"
import {
  approvalBlocked,
  approvalDecided,
  approvalRequested,
  comparisonCreated,
  evidenceLoaded,
  sessionFailed,
  simulationCompleted,
} from "./workflow-late"
import type {
  WorkflowAction,
  WorkflowState,
  WorkflowStorage,
  WorkflowStore,
  WorkflowTransition,
} from "./workflow-types"

export { deriveLifecycleResourceGraph } from "./workflow-graph"
export type {
  ActiveState,
  ApprovalBlockedState,
  ApprovalPendingState,
  ComparisonState,
  DecisionState,
  DiagnosisState,
  EvidenceState,
  LifecycleResourceGraph,
  LifecycleResourceGraphEdge,
  LifecycleResourceGraphNode,
  PatchState,
  ScenarioState,
  SimulationState,
  WorkflowAction,
  WorkflowState,
  WorkflowStore,
  WorkflowTransition,
  WorkflowTransitionError,
} from "./workflow-types"
export { WORKFLOW_PHASES } from "./workflow-types"

function assertNever(value: never): never {
  throw new TypeError(`Unhandled workflow action: ${String(value)}`)
}

export function transitionWorkflow(
  state: WorkflowState,
  action: WorkflowAction,
  storage: WorkflowStorage = createSessionStorageAdapter(),
): WorkflowTransition {
  switch (action.type) {
    case "bootstrap_started":
      return bootstrapStarted(state, action)
    case "bootstrap_succeeded":
      return bootstrapSucceeded(state, action, storage)
    case "scenario_created":
      return scenarioCreated(state, action, storage)
    case "diagnosis_recorded":
      return diagnosisRecorded(state, action)
    case "patch_proposed":
      return patchProposed(state, action, storage)
    case "simulation_completed":
      return simulationCompleted(state, action, storage)
    case "comparison_created":
      return comparisonCreated(state, action, storage)
    case "approval_requested":
      return approvalRequested(state, action, storage)
    case "approval_blocked":
      return approvalBlocked(state, action)
    case "approval_decided":
      return approvalDecided(state, action)
    case "evidence_loaded":
      return evidenceLoaded(state, action)
    case "session_failed":
      return sessionFailed(state, action)
    default:
      return assertNever(action)
  }
}

export function createWorkflowStore(
  options: { readonly storage?: SessionStorageAdapter; readonly initialState?: WorkflowState } = {},
): WorkflowStore {
  const storage = options.storage ?? createSessionStorageAdapter()
  let state: WorkflowState = options.initialState ?? { phase: "no-session" }
  return {
    getState: () => state,
    dispatch: (action) => {
      const result = transitionWorkflow(state, action, storage)
      if (result.ok) state = result.state
      return result
    },
    storage,
  }
}
