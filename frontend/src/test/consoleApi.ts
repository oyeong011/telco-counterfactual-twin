import type { ApiClient } from "../api/client"
import { transportFailure } from "../api/errors"
import type { IdempotencyKey } from "../api/idempotency"
import { canonicalSha256 } from "../contracts/canonical-json"
import {
  type ApiFailure,
  type ApiResult,
  ApprovalDecisionResponseSchema,
  type BenchmarkRequest,
  BenchmarkResponseSchema,
  ContractIdSchema,
  type Event,
  EventSchema,
  type EventType,
  EventTypeSchema,
  EvidenceResponseSchema,
  type ScenarioCreateRequest,
} from "../contracts/generated"
import {
  approval,
  comparison,
  diagnosis,
  HASHES,
  patch,
  scenario,
  session,
  simulation,
} from "../state/workflow-fixtures"

const META = { requestId: "request-test-001", replayed: false } as const
const success = <T>(data: T): Promise<ApiResult<T>> =>
  Promise.resolve({ ok: true, data, meta: META })

type FixtureOptions = {
  readonly bootstrapException?: Error
  readonly bootstrapFailure?: ApiFailure
  readonly diagnosisFailure?: ApiFailure
  readonly diagnosisGate?: Promise<void>
  readonly patchFailure?: ApiFailure
  readonly policyFailure?: ApiFailure
}

export type ConsoleApiFixture = {
  readonly client: ApiClient
  readonly idempotencyKeys: readonly IdempotencyKey[]
  readonly callCounts: { diagnosis: number }
  readonly scenarioInputs: ScenarioCreateRequest[]
  readonly benchmarkInputs: BenchmarkRequest[]
}

function lifecycleEvent(
  eventId: string,
  sequenceId: number,
  eventType: EventType,
  resourceId: string,
): Event {
  return EventSchema.parse({
    schema_version: "1.0",
    event_id: eventId,
    scenario_id: scenario.scenario.scenario_id,
    timestamp: `2026-08-28T00:00:0${sequenceId}Z`,
    priority: 0,
    sequence_id: sequenceId,
    event_type: eventType,
    payload: {
      request_hash: HASHES.constraint,
      resource_id: resourceId,
      run_id: scenario.run_id,
      status: "recorded",
    },
  })
}

export function createConsoleApiFixture(options: FixtureOptions = {}): ConsoleApiFixture {
  const keys: IdempotencyKey[] = []
  let submittedPatchId = patch.patch.patch_id
  let terminalDecision: "approved" | "rejected" = "rejected"
  const callCounts = { diagnosis: 0 }
  const scenarioInputs: ScenarioCreateRequest[] = []
  const benchmarkInputs: BenchmarkRequest[] = []
  const remember = (key: IdempotencyKey): void => {
    keys.push(key)
  }
  const failure = options.bootstrapFailure ?? transportFailure("request-unused")

  const client: ApiClient = {
    baseUrl: "http://api.test/",
    timeoutMs: 10_000,
    bootstrapDemoSession: () => {
      if (options.bootstrapException) return Promise.reject(options.bootstrapException)
      return options.bootstrapFailure ? Promise.resolve(options.bootstrapFailure) : success(session)
    },
    getHealth: () => success({ status: "live" }),
    getReadiness: () => success({ status: "ready", checks: { state_store: true } }),
    getBuildInfo: () => Promise.resolve(failure),
    getApprovalRoot: () => Promise.resolve(failure),
    listScenarios: () => success({ items: [] }),
    createScenario: (_auth, key, input) => {
      remember(key)
      scenarioInputs.push(input)
      return success(scenario)
    },
    getScenario: () => success(scenario),
    diagnoseScenario: async (_auth, key) => {
      remember(key)
      callCounts.diagnosis += 1
      await options.diagnosisGate
      return options.diagnosisFailure
        ? options.diagnosisFailure
        : { ok: true, data: diagnosis, meta: META }
    },
    proposePatch: (_auth, key, _scenarioId, submitted) => {
      remember(key)
      submittedPatchId = submitted.patch_id
      return options.patchFailure
        ? Promise.resolve(options.patchFailure)
        : success({ ...patch, patch: submitted })
    },
    createSimulation: (_auth, key) => {
      remember(key)
      return success({ ...simulation, patch_id: submittedPatchId })
    },
    getSimulation: () => success({ simulation, result: comparison.comparison.result }),
    compareSimulation: (_auth, key) => {
      remember(key)
      return success(comparison)
    },
    requestApproval: (_auth, key) => {
      remember(key)
      return options.policyFailure ? Promise.resolve(options.policyFailure) : success(approval)
    },
    getApprovalRequest: () =>
      success({ approval_request: approval.approval_request, state: "pending", proof_hash: null }),
    approveWithDemo: (_auth, key) => {
      remember(key)
      terminalDecision = "approved"
      return success(decisionResponse("approved"))
    },
    rejectWithDemo: (_auth, key) => {
      remember(key)
      terminalDecision = "rejected"
      return success(decisionResponse("rejected"))
    },
    approveWithJwt: () => Promise.resolve(failure),
    rejectWithJwt: () => Promise.resolve(failure),
    getRunEvidence: () => success(evidenceResponse(terminalDecision, submittedPatchId)),
    runBenchmark: (_auth, key, input) => {
      remember(key)
      benchmarkInputs.push(input)
      return success(
        BenchmarkResponseSchema.parse({
          ...input,
          unique_trace_hashes: 1,
          deterministic: true,
          trace_hash: HASHES.candidateTrace,
        }),
      )
    },
    streamRunEvents: async function* () {
      for (const event of evidenceEvents(terminalDecision, submittedPatchId)) {
        yield { id: event.event_id, event: EventTypeSchema.parse(event.event_type), data: event }
      }
    },
  }
  return { client, idempotencyKeys: keys, callCounts, scenarioInputs, benchmarkInputs }
}

function decisionResponse(decision: "approved" | "rejected") {
  return ApprovalDecisionResponseSchema.parse({
    state: decision,
    approval_proof: {
      proof_id: "approval-proof-001",
      approval_request_id: approval.approval_request.request_id,
      session_id: session.session_id,
      session_key_id: session.session_certificate.session_key_id,
      patch_hash: HASHES.patch,
      simulation_hash: HASHES.simulation,
      policy_hash: HASHES.policy,
      nonce: approval.approval_request.nonce,
      decision,
      approved_at: approval.approval_request.requested_at,
      expires_at: approval.approval_request.expires_at,
      certificate_hash: HASHES.certificate,
      proof_signature: "A".repeat(86),
      schema_version: "1.0",
    },
    effect: "evidence-only",
  })
}

function evidenceEvents(decision: "approved" | "rejected", patchId: string): readonly Event[] {
  const terminalEvent: EventType =
    decision === "approved" ? "approval-approved" : "approval-rejected"
  return [
    lifecycleEvent("event-001", 0, "scenario-created", "scenario-001"),
    lifecycleEvent("event-002", 1, "scenario-diagnosed", "diagnosis-001"),
    lifecycleEvent("event-003", 2, "patch-proposed", patchId),
    lifecycleEvent("event-004", 3, "simulation-completed", "simulation-001"),
    lifecycleEvent("event-005", 4, "comparison-created", "comparison-001"),
    lifecycleEvent("event-006", 5, "approval-requested", "approval-request-001"),
    lifecycleEvent("event-007", 6, terminalEvent, "approval-proof-001"),
  ]
}

function evidenceResponse(decision: "approved" | "rejected", patchId: string) {
  const proof = decisionResponse(decision).approval_proof
  return EvidenceResponseSchema.parse({
    run_id: scenario.run_id,
    evidence_card: {
      schema_version: "1.0",
      evidence_id: approval.evidence_id,
      session_id: session.session_id,
      scenario_hash: HASHES.scenario,
      patch_hash: HASHES.patch,
      simulation_hash: HASHES.simulation,
      policy_hash: HASHES.policy,
      approval_proof_hash: canonicalSha256(proof),
      seed: scenario.scenario.seed,
      source_commit_sha: "b".repeat(40),
      contract_hashes: { scenario: HASHES.scenario },
      generated_at: "2026-08-28T00:00:06Z",
    },
    events: evidenceEvents(decision, ContractIdSchema.parse(patchId)),
    approval_proof: proof,
  })
}
