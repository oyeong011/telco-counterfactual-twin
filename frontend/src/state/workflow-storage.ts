import type {
  ApprovalRequestResponse,
  ComparisonResponse,
  PatchResponse,
  ScenarioResponse,
  SimulationResponse,
} from "../contracts/generated"
import type { RunDraftIndex, SessionStorageAdapter } from "./session"
import type { ActiveState } from "./workflow-types"

export function storeScenario(
  storage: SessionStorageAdapter,
  response: ScenarioResponse,
): RunDraftIndex {
  const draft: RunDraftIndex = {
    runId: response.run_id,
    scenarioId: response.scenario.scenario_id,
  }
  storage.saveRunDraft(draft)
  return draft
}

export function storePatch(
  storage: SessionStorageAdapter,
  state: ActiveState,
  response: PatchResponse,
  submittedPatch: PatchResponse["patch"] | undefined,
): RunDraftIndex {
  const draft: RunDraftIndex = {
    ...state.run,
    patchId: response.patch.patch_id,
    patchBody: submittedPatch ?? response.patch,
  }
  storage.saveRunDraft(draft)
  return draft
}

export function storeSimulation(
  storage: SessionStorageAdapter,
  state: ActiveState,
  response: SimulationResponse,
): RunDraftIndex {
  const draft: RunDraftIndex = { ...state.run, simulationId: response.simulation_id }
  storage.saveRunDraft(draft)
  return draft
}

export function storeComparison(
  storage: SessionStorageAdapter,
  state: ActiveState,
  response: ComparisonResponse,
): RunDraftIndex {
  const draft: RunDraftIndex = { ...state.run, comparisonId: response.comparison_id }
  storage.saveRunDraft(draft)
  return draft
}

export function storeApproval(
  storage: SessionStorageAdapter,
  state: ActiveState,
  response: ApprovalRequestResponse,
): RunDraftIndex {
  const draft: RunDraftIndex = {
    ...state.run,
    approvalRequestId: response.approval_request.request_id,
  }
  storage.saveRunDraft(draft)
  return draft
}
