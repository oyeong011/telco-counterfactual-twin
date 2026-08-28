import type {
  ApiFailure,
  ApprovalDecisionResponse,
  ApprovalRequestResponse,
  ComparisonResponse,
  ContractId,
  DemoSessionResponse,
  DiagnosisResponse,
  EvidenceResponse,
  PatchResponse,
  ScenarioResponse,
  SimulationResponse,
  TypedPatch,
} from "../contracts/generated"
import type { RunDraftIndex, SessionStorageAdapter } from "./session"

export type ActiveState = {
  readonly session: DemoSessionResponse
  readonly run: RunDraftIndex
}
export const WORKFLOW_PHASES = [
  "no-session",
  "bootstrapping",
  "session-active",
  "scenario",
  "diagnosis",
  "patch",
  "simulation",
  "comparison",
  "approval-pending",
  "approval-blocked",
  "decision",
  "evidence",
  "session-error",
] as const
export type WorkflowPhase = (typeof WORKFLOW_PHASES)[number]
export type ScenarioState = ActiveState & { readonly scenario: ScenarioResponse }
export type DiagnosisState = ScenarioState & { readonly diagnosis: DiagnosisResponse }
export type PatchState = DiagnosisState & { readonly patch: PatchResponse }
export type SimulationState = PatchState & { readonly simulation: SimulationResponse }
export type ComparisonState = SimulationState & { readonly comparison: ComparisonResponse }
export type ApprovalPendingState = ComparisonState & { readonly approval: ApprovalRequestResponse }
export type ApprovalBlockedState = ComparisonState & { readonly problem: ApiFailure }
export type DecisionState = ApprovalPendingState & { readonly decision: ApprovalDecisionResponse }
export type EvidenceState = DecisionState & { readonly evidence: EvidenceResponse }

export type WorkflowState =
  | { readonly phase: "no-session" }
  | { readonly phase: "bootstrapping" }
  | {
      readonly phase: "session-active"
      readonly session: DemoSessionResponse
      readonly drafts: readonly RunDraftIndex[]
    }
  | ({ readonly phase: "scenario" } & ScenarioState)
  | ({ readonly phase: "diagnosis" } & DiagnosisState)
  | ({ readonly phase: "patch" } & PatchState)
  | ({ readonly phase: "simulation" } & SimulationState)
  | ({ readonly phase: "comparison" } & ComparisonState)
  | ({ readonly phase: "approval-pending" } & ApprovalPendingState)
  | ({ readonly phase: "approval-blocked" } & ApprovalBlockedState)
  | ({ readonly phase: "decision" } & DecisionState)
  | ({ readonly phase: "evidence" } & EvidenceState)
  | { readonly phase: "session-error"; readonly failure: ApiFailure }

export type WorkflowAction =
  | { readonly type: "bootstrap_started" }
  | { readonly type: "bootstrap_succeeded"; readonly session: DemoSessionResponse }
  | { readonly type: "scenario_created"; readonly response: ScenarioResponse }
  | { readonly type: "diagnosis_recorded"; readonly response: DiagnosisResponse }
  | {
      readonly type: "patch_proposed"
      readonly response: PatchResponse
      readonly submittedPatch: TypedPatch
    }
  | { readonly type: "simulation_completed"; readonly response: SimulationResponse }
  | { readonly type: "comparison_created"; readonly response: ComparisonResponse }
  | { readonly type: "approval_requested"; readonly response: ApprovalRequestResponse }
  | { readonly type: "approval_blocked"; readonly problem: ApiFailure }
  | { readonly type: "approval_decided"; readonly response: ApprovalDecisionResponse }
  | { readonly type: "evidence_loaded"; readonly response: EvidenceResponse }
  | { readonly type: "session_failed"; readonly failure: ApiFailure }

export type WorkflowTransitionError = {
  readonly kind: "illegal_transition"
  readonly phase: WorkflowState["phase"]
  readonly action: WorkflowAction["type"]
}

export type WorkflowTransition =
  | { readonly ok: true; readonly state: WorkflowState }
  | { readonly ok: false; readonly error: WorkflowTransitionError }

export type WorkflowStorage = SessionStorageAdapter

export type LifecycleResourceGraphNode = {
  readonly id: ContractId
  readonly eventId: ContractId
  readonly eventType: string
  readonly sequenceId: number
}
export type LifecycleResourceGraphEdge = {
  readonly id: ContractId
  readonly sourceId: ContractId
  readonly targetId: ContractId
  readonly relation: "observed-next"
}
export type LifecycleResourceGraph = {
  readonly kind: "lifecycle-resource-graph"
  readonly topology: {
    readonly kind: "unavailable"
    readonly reason: "no-http-topology-read-contract"
  }
  readonly nodes: readonly LifecycleResourceGraphNode[]
  readonly edges: readonly LifecycleResourceGraphEdge[]
}

export type WorkflowStore = {
  readonly getState: () => WorkflowState
  readonly dispatch: (action: WorkflowAction) => WorkflowTransition
  readonly storage: SessionStorageAdapter
}
