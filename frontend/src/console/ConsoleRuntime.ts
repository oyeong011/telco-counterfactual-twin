import { type ApiClient, sessionAuthFromResponse } from "../api/client"
import { contractFailure, sessionGateForProblem } from "../api/errors"
import { generateIdempotencyKey } from "../api/idempotency"
import type { BenchmarkRequest, ScenarioCreateRequest, TypedPatch } from "../contracts/generated"
import { createWorkflowStore, type WorkflowAction, type WorkflowStore } from "../state/workflow"
import type { ConsoleModel, ConsoleOperation } from "./console-model"
import { snapshotFromWorkflow } from "./console-model"
import { replayRunEvents } from "./runtime-events"

export class ConsoleRuntime {
  private workflowStore: WorkflowStore = createWorkflowStore()
  private scenarios: ConsoleModel["scenarios"] = []
  private events: ConsoleModel["events"] = []
  private benchmark: ConsoleModel["benchmark"] = null
  private failure: ConsoleModel["failure"] = null
  private validationIssue: ConsoleModel["validationIssue"] = null
  private busy: ConsoleModel["busy"] = null

  constructor(private readonly client: ApiClient) {}

  getModel(): ConsoleModel {
    const workflow = this.workflowStore.getState()
    return {
      workflow,
      snapshot: snapshotFromWorkflow(workflow),
      scenarios: this.scenarios,
      events: this.events,
      benchmark: this.benchmark,
      failure: this.failure,
      validationIssue: this.validationIssue,
      busy: this.busy,
    }
  }

  setBusy(operation: ConsoleOperation | null): void {
    this.busy = operation
  }

  clearTransient(): void {
    this.failure = null
    this.validationIssue = null
  }

  setValidationIssue(issue: string): void {
    this.failure = null
    this.validationIssue = issue
  }

  recordContractFailure(): void {
    this.recordFailure(contractFailure(), this.workflowStore.getState().phase === "bootstrapping")
  }

  reset(): void {
    const sessionId = this.getModel().snapshot.session?.session_id
    if (sessionId !== undefined) this.workflowStore.storage.resetRunDrafts(sessionId)
    this.workflowStore = createWorkflowStore()
    this.scenarios = []
    this.events = []
    this.benchmark = null
    this.failure = null
    this.validationIssue = null
    this.busy = null
  }

  async bootstrap(): Promise<void> {
    if (!this.commit({ type: "bootstrap_started" })) return
    const result = await this.client.bootstrapDemoSession()
    if (!result.ok) {
      this.recordFailure(result, true)
      return
    }
    if (!this.commit({ type: "bootstrap_succeeded", session: result.data })) return
    await this.refreshScenarios()
  }

  async refreshScenarios(): Promise<void> {
    const session = this.getModel().snapshot.session
    if (session === undefined) return
    const result = await this.client.listScenarios(sessionAuthFromResponse(session))
    if (!result.ok) {
      this.recordFailure(result)
      return
    }
    this.scenarios = result.data.items
  }

  async createScenario(input: ScenarioCreateRequest): Promise<void> {
    const session = this.getModel().snapshot.session
    if (session === undefined) return this.missingSession()
    const result = await this.client.createScenario(
      sessionAuthFromResponse(session),
      generateIdempotencyKey(),
      input,
    )
    if (!result.ok) return this.recordFailure(result)
    if (!this.commit({ type: "scenario_created", response: result.data })) return
    this.scenarios = [...this.scenarios, result.data]
  }

  async diagnose(): Promise<void> {
    const model = this.getModel()
    if (model.snapshot.session === undefined || model.snapshot.scenario === undefined)
      return this.missingSession()
    const result = await this.client.diagnoseScenario(
      sessionAuthFromResponse(model.snapshot.session),
      generateIdempotencyKey(),
      model.snapshot.scenario.scenario.scenario_id,
    )
    if (!result.ok) return this.recordFailure(result)
    this.commit({ type: "diagnosis_recorded", response: result.data })
  }

  async proposePatch(patch: TypedPatch): Promise<void> {
    const model = this.getModel()
    if (model.snapshot.session === undefined || model.snapshot.scenario === undefined)
      return this.missingSession()
    const result = await this.client.proposePatch(
      sessionAuthFromResponse(model.snapshot.session),
      generateIdempotencyKey(),
      model.snapshot.scenario.scenario.scenario_id,
      patch,
    )
    if (!result.ok) return this.recordFailure(result)
    this.commit({ type: "patch_proposed", response: result.data, submittedPatch: patch })
  }

  async simulate(): Promise<void> {
    const model = this.getModel()
    if (model.snapshot.session === undefined || model.snapshot.patch === undefined)
      return this.missingSession()
    const result = await this.client.createSimulation(
      sessionAuthFromResponse(model.snapshot.session),
      generateIdempotencyKey(),
      model.snapshot.patch.patch.patch_id,
    )
    if (!result.ok) return this.recordFailure(result)
    this.commit({ type: "simulation_completed", response: result.data })
  }

  async compare(): Promise<void> {
    const model = this.getModel()
    if (model.snapshot.session === undefined || model.snapshot.simulation === undefined)
      return this.missingSession()
    const result = await this.client.compareSimulation(
      sessionAuthFromResponse(model.snapshot.session),
      generateIdempotencyKey(),
      model.snapshot.simulation.simulation_id,
    )
    if (!result.ok) return this.recordFailure(result)
    this.commit({ type: "comparison_created", response: result.data })
  }

  async requestApproval(): Promise<void> {
    const model = this.getModel()
    if (model.snapshot.session === undefined || model.snapshot.simulation === undefined)
      return this.missingSession()
    const result = await this.client.requestApproval(
      sessionAuthFromResponse(model.snapshot.session),
      generateIdempotencyKey(),
      model.snapshot.simulation.simulation_id,
    )
    if (!result.ok) {
      if (result.problem.code === "policy_ineligible")
        this.commit({ type: "approval_blocked", problem: result })
      this.recordFailure(result)
      return
    }
    this.commit({ type: "approval_requested", response: result.data })
  }

  async decide(decision: "approve" | "reject"): Promise<void> {
    const model = this.getModel()
    if (model.snapshot.session === undefined || model.snapshot.approval === undefined)
      return this.missingSession()
    const auth = sessionAuthFromResponse(model.snapshot.session)
    const key = generateIdempotencyKey()
    const requestId = model.snapshot.approval.approval_request.request_id
    const result =
      decision === "approve"
        ? await this.client.approveWithDemo(auth, key, requestId)
        : await this.client.rejectWithDemo(auth, key, requestId)
    if (!result.ok) return this.recordFailure(result)
    this.commit({ type: "approval_decided", response: result.data })
  }

  async loadEvidence(): Promise<void> {
    const model = this.getModel()
    if (model.snapshot.session === undefined || model.snapshot.run === undefined)
      return this.missingSession()
    const result = await this.client.getRunEvidence(
      sessionAuthFromResponse(model.snapshot.session),
      model.snapshot.run.runId,
    )
    if (!result.ok) return this.recordFailure(result)
    this.commit({ type: "evidence_loaded", response: result.data })
    this.events = result.data.events
  }

  async replayEvents(): Promise<void> {
    const model = this.getModel()
    if (model.snapshot.session === undefined || model.snapshot.run === undefined)
      return this.missingSession()
    const result = await replayRunEvents(
      this.client,
      sessionAuthFromResponse(model.snapshot.session),
      model.snapshot.run.runId,
    )
    if (!result.ok) return this.recordFailure(result.failure)
    this.events = result.events
  }

  async runBenchmark(input: BenchmarkRequest): Promise<void> {
    const session = this.getModel().snapshot.session
    if (session === undefined) return this.missingSession()
    const result = await this.client.runBenchmark(
      sessionAuthFromResponse(session),
      generateIdempotencyKey(),
      input,
    )
    if (!result.ok) return this.recordFailure(result)
    this.benchmark = result.data
  }

  private commit(action: WorkflowAction): boolean {
    const result = this.workflowStore.dispatch(action)
    if (result.ok) return true
    this.validationIssue = `Response rejected at ${result.error.phase}: ${result.error.action}.`
    return false
  }

  private recordFailure(failure: NonNullable<ConsoleModel["failure"]>, terminal = false): void {
    this.failure = failure
    const gate = sessionGateForProblem(failure.problem)
    if (terminal || gate !== null) {
      const sessionId = this.getModel().snapshot.session?.session_id
      if (sessionId !== undefined) this.workflowStore.storage.resetRunDrafts(sessionId)
      this.commit({ type: "session_failed", failure })
      this.scenarios = []
      this.events = []
      this.benchmark = null
    }
  }

  private missingSession(): void {
    this.validationIssue = "This action requires an in-memory demo session."
  }
}
