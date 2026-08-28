import {
  approvalDecisionBindsToState,
  approvalRequestBindsToState,
  comparisonBindsToState,
  evidenceBindsToState,
} from "./workflow-bindings"
import { storeApproval, storeComparison, storeSimulation } from "./workflow-storage"
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

export function simulationCompleted(
  state: WorkflowState,
  action: Extract<WorkflowAction, { readonly type: "simulation_completed" }>,
  storage: WorkflowStorage,
): WorkflowTransition {
  if (state.phase !== "patch") return illegal(state, action)
  if (
    action.response.patch_id !== state.patch.patch.patch_id ||
    action.response.scenario_id !== state.scenario.scenario.scenario_id ||
    action.response.run_id !== state.run.runId
  )
    return illegal(state, action)
  return {
    ok: true,
    state: {
      phase: "simulation",
      session: state.session,
      run: storeSimulation(storage, state, action.response),
      scenario: state.scenario,
      diagnosis: state.diagnosis,
      patch: state.patch,
      simulation: action.response,
    },
  }
}

export function comparisonCreated(
  state: WorkflowState,
  action: Extract<WorkflowAction, { readonly type: "comparison_created" }>,
  storage: WorkflowStorage,
): WorkflowTransition {
  if (state.phase !== "simulation") return illegal(state, action)
  if (!comparisonBindsToState(state, action.response)) return illegal(state, action)
  return {
    ok: true,
    state: {
      phase: "comparison",
      session: state.session,
      run: storeComparison(storage, state, action.response),
      scenario: state.scenario,
      diagnosis: state.diagnosis,
      patch: state.patch,
      simulation: state.simulation,
      comparison: action.response,
    },
  }
}

export function approvalRequested(
  state: WorkflowState,
  action: Extract<WorkflowAction, { readonly type: "approval_requested" }>,
  storage: WorkflowStorage,
): WorkflowTransition {
  if (state.phase !== "comparison") return illegal(state, action)
  if (!action.response.policy.eligible || !approvalRequestBindsToState(state, action.response))
    return illegal(state, action)
  return {
    ok: true,
    state: {
      phase: "approval-pending",
      session: state.session,
      run: storeApproval(storage, state, action.response),
      scenario: state.scenario,
      diagnosis: state.diagnosis,
      patch: state.patch,
      simulation: state.simulation,
      comparison: state.comparison,
      approval: action.response,
    },
  }
}

export function approvalBlocked(
  state: WorkflowState,
  action: Extract<WorkflowAction, { readonly type: "approval_blocked" }>,
): WorkflowTransition {
  if (
    state.phase !== "comparison" ||
    state.comparison.run_id !== state.run.runId ||
    action.problem.problem.code !== "policy_ineligible"
  )
    return illegal(state, action)
  return {
    ok: true,
    state: {
      phase: "approval-blocked",
      session: state.session,
      run: state.run,
      scenario: state.scenario,
      diagnosis: state.diagnosis,
      patch: state.patch,
      simulation: state.simulation,
      comparison: state.comparison,
      problem: action.problem,
    },
  }
}

export function approvalDecided(
  state: WorkflowState,
  action: Extract<WorkflowAction, { readonly type: "approval_decided" }>,
): WorkflowTransition {
  if (state.phase !== "approval-pending") return illegal(state, action)
  if (!approvalDecisionBindsToState(state, action.response)) return illegal(state, action)
  return {
    ok: true,
    state: {
      phase: "decision",
      session: state.session,
      run: state.run,
      scenario: state.scenario,
      diagnosis: state.diagnosis,
      patch: state.patch,
      simulation: state.simulation,
      comparison: state.comparison,
      approval: state.approval,
      decision: action.response,
    },
  }
}

export function evidenceLoaded(
  state: WorkflowState,
  action: Extract<WorkflowAction, { readonly type: "evidence_loaded" }>,
): WorkflowTransition {
  if (state.phase !== "decision") return illegal(state, action)
  if (!evidenceBindsToState(state, action.response)) return illegal(state, action)
  return {
    ok: true,
    state: {
      phase: "evidence",
      session: state.session,
      run: state.run,
      scenario: state.scenario,
      diagnosis: state.diagnosis,
      patch: state.patch,
      simulation: state.simulation,
      comparison: state.comparison,
      approval: state.approval,
      decision: state.decision,
      evidence: action.response,
    },
  }
}

export function sessionFailed(
  state: WorkflowState,
  action: Extract<WorkflowAction, { readonly type: "session_failed" }>,
): WorkflowTransition {
  return state.phase === "no-session"
    ? illegal(state, action)
    : { ok: true, state: { phase: "session-error", failure: action.failure } }
}
