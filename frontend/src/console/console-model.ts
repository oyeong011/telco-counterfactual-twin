import type {
  ApiFailure,
  ApprovalDecisionResponse,
  ApprovalRequestResponse,
  BenchmarkResponse,
  ComparisonResponse,
  DemoSessionResponse,
  DiagnosisResponse,
  Event,
  EvidenceResponse,
  PatchResponse,
  ScenarioResponse,
  SimulationResponse,
} from "../contracts/generated"
import type { RunDraftIndex } from "../state/session"
import type { WorkflowState } from "../state/workflow"

const CONSOLE_OPERATIONS = [
  "bootstrap",
  "scenario",
  "diagnosis",
  "patch",
  "simulation",
  "comparison",
  "approval",
  "decision",
  "evidence",
  "events",
  "benchmark",
] as const
export type ConsoleOperation = (typeof CONSOLE_OPERATIONS)[number]

export type WorkflowSnapshot = {
  readonly session?: DemoSessionResponse
  readonly run?: RunDraftIndex
  readonly scenario?: ScenarioResponse
  readonly diagnosis?: DiagnosisResponse
  readonly patch?: PatchResponse
  readonly simulation?: SimulationResponse
  readonly comparison?: ComparisonResponse
  readonly approval?: ApprovalRequestResponse
  readonly decision?: ApprovalDecisionResponse
  readonly evidence?: EvidenceResponse
}

export type ConsoleModel = {
  readonly workflow: WorkflowState
  readonly snapshot: WorkflowSnapshot
  readonly scenarios: readonly ScenarioResponse[]
  readonly events: readonly Event[]
  readonly benchmark: BenchmarkResponse | null
  readonly failure: ApiFailure | null
  readonly validationIssue: string | null
  readonly busy: ConsoleOperation | null
}

export function snapshotFromWorkflow(state: WorkflowState): WorkflowSnapshot {
  switch (state.phase) {
    case "no-session":
    case "bootstrapping":
    case "session-error":
      return {}
    case "session-active":
      return { session: state.session }
    case "scenario":
      return { session: state.session, run: state.run, scenario: state.scenario }
    case "diagnosis":
      return {
        ...snapshotFromWorkflow({ ...state, phase: "scenario" }),
        diagnosis: state.diagnosis,
      }
    case "patch":
      return {
        session: state.session,
        run: state.run,
        scenario: state.scenario,
        diagnosis: state.diagnosis,
        patch: state.patch,
      }
    case "simulation":
      return {
        session: state.session,
        run: state.run,
        scenario: state.scenario,
        diagnosis: state.diagnosis,
        patch: state.patch,
        simulation: state.simulation,
      }
    case "comparison":
    case "approval-blocked":
      return {
        session: state.session,
        run: state.run,
        scenario: state.scenario,
        diagnosis: state.diagnosis,
        patch: state.patch,
        simulation: state.simulation,
        comparison: state.comparison,
      }
    case "approval-pending":
      return {
        session: state.session,
        run: state.run,
        scenario: state.scenario,
        diagnosis: state.diagnosis,
        patch: state.patch,
        simulation: state.simulation,
        comparison: state.comparison,
        approval: state.approval,
      }
    case "decision":
      return {
        session: state.session,
        run: state.run,
        scenario: state.scenario,
        diagnosis: state.diagnosis,
        patch: state.patch,
        simulation: state.simulation,
        comparison: state.comparison,
        approval: state.approval,
        decision: state.decision,
      }
    case "evidence":
      return {
        session: state.session,
        run: state.run,
        scenario: state.scenario,
        diagnosis: state.diagnosis,
        patch: state.patch,
        simulation: state.simulation,
        comparison: state.comparison,
        approval: state.approval,
        decision: state.decision,
        evidence: state.evidence,
      }
  }
}
