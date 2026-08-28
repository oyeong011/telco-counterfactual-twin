import ky from "ky"
import {
  type ApiFailure,
  ApprovalDecisionResponseSchema,
  ApprovalReadResponseSchema,
  ApprovalRequestResponseSchema,
  BenchmarkRequestSchema,
  BenchmarkResponseSchema,
  ComparisonResponseSchema,
  type ContractId,
  DemoSessionResponseSchema,
  DiagnosisResponseSchema,
  EvidenceResponseSchema,
  HealthResponseSchema,
  PatchResponseSchema,
  ReadyResponseSchema,
  RootDescriptorSchema,
  ScenarioCreateRequestSchema,
  ScenarioListResponseSchema,
  ScenarioResponseSchema,
  ServiceBuildInfoSchema,
  SimulationReadResponseSchema,
  SimulationResponseSchema,
  TypedPatchSchema,
} from "../contracts/generated"
import { JwtTokenSchema, type SessionAuth } from "./auth"
import { API_GET_RETRY_LIMIT, API_TIMEOUT_MS, createApiTransport } from "./client-transport"
import type { ApiClient, ApiClientOptions } from "./client-types"
import { contractFailure } from "./errors"
import { evidenceProofHashMatches } from "./evidence-integrity"
import { type SseFrame, streamRunEvents } from "./sse"
import { resolveApiBaseUrl } from "./url"

export {
  type DemoToken,
  DemoTokenSchema,
  type JwtToken,
  JwtTokenSchema,
  type SessionAuth,
  sessionAuthFromResponse,
} from "./auth"
export { API_GET_RETRY_LIMIT, API_TIMEOUT_MS } from "./client-transport"
export type { ApiClient, ApiClientOptions } from "./client-types"

export function createApiClient(options: ApiClientOptions = {}): ApiClient {
  const baseUrl = resolveApiBaseUrl(options.baseUrl)
  const http = ky.create({
    prefix: baseUrl,
    timeout: API_TIMEOUT_MS,
    throwHttpErrors: false,
    retry: { limit: API_GET_RETRY_LIMIT, methods: ["get"], delay: () => 0 },
    ...(options.fetch ? { fetch: options.fetch } : {}),
  })
  const transport = createApiTransport(http)
  const request = transport.request
  const emptyBody = transport.emptyBody
  const withKey = transport.withKey
  const runEvents = (
    session: SessionAuth,
    runId: ContractId,
    lastEventId?: ContractId,
    signal?: AbortSignal,
  ): AsyncGenerator<SseFrame | ApiFailure> => {
    const streamOptions = {
      baseUrl,
      sessionToken: session.demoToken,
      runId,
      ...(lastEventId ? { lastEventId } : {}),
      ...(signal ? { signal } : {}),
      ...(options.fetch ? { fetch: options.fetch } : {}),
    }
    return streamRunEvents(streamOptions)
  }
  const getRunEvidence: ApiClient["getRunEvidence"] = async (session, runId) => {
    const result = await request("get", `api/runs/${runId}/evidence`, EvidenceResponseSchema, {
      session,
    })
    if (!result.ok) return result
    return (await evidenceProofHashMatches(result.data))
      ? result
      : contractFailure(result.meta.requestId)
  }

  return {
    baseUrl,
    timeoutMs: API_TIMEOUT_MS,
    bootstrapDemoSession: () =>
      request(
        "post",
        "api/demo-sessions",
        DemoSessionResponseSchema,
        {},
        { synthetic_only: true },
        [201],
      ),
    getHealth: () => request("get", "healthz", HealthResponseSchema),
    getReadiness: () => request("get", "readyz", ReadyResponseSchema, {}, undefined, [200, 503]),
    getBuildInfo: () => request("get", "build-info", ServiceBuildInfoSchema),
    getApprovalRoot: () => request("get", ".well-known/approval-root", RootDescriptorSchema),
    listScenarios: (session) =>
      request("get", "api/scenarios", ScenarioListResponseSchema, { session }),
    createScenario: (session, key, input) =>
      request(
        "post",
        "api/scenarios",
        ScenarioResponseSchema,
        { session, key: withKey(key) },
        ScenarioCreateRequestSchema.parse(input),
        [201],
      ),
    getScenario: (session, scenarioId) =>
      request("get", `api/scenarios/${scenarioId}`, ScenarioResponseSchema, { session }),
    diagnoseScenario: (session, key, scenarioId) =>
      request(
        "post",
        `api/scenarios/${scenarioId}/diagnose`,
        DiagnosisResponseSchema,
        { session, key: withKey(key) },
        emptyBody(),
      ),
    proposePatch: (session, key, scenarioId, patch) =>
      request(
        "post",
        `api/scenarios/${scenarioId}/patches`,
        PatchResponseSchema,
        { session, key: withKey(key) },
        TypedPatchSchema.parse(patch),
        [201],
      ),
    createSimulation: (session, key, patchId) =>
      request(
        "post",
        `api/patches/${patchId}/simulations`,
        SimulationResponseSchema,
        { session, key: withKey(key) },
        emptyBody(),
        [201],
      ),
    getSimulation: (session, simulationId) =>
      request("get", `api/simulations/${simulationId}`, SimulationReadResponseSchema, { session }),
    compareSimulation: (session, key, simulationId) =>
      request(
        "post",
        `api/simulations/${simulationId}/comparisons`,
        ComparisonResponseSchema,
        { session, key: withKey(key) },
        emptyBody(),
        [201],
      ),
    requestApproval: (session, key, simulationId) =>
      request(
        "post",
        `api/simulations/${simulationId}/approval-requests`,
        ApprovalRequestResponseSchema,
        { session, key: withKey(key) },
        emptyBody(),
        [201],
      ),
    getApprovalRequest: (session, approvalRequestId) =>
      request("get", `api/approval-requests/${approvalRequestId}`, ApprovalReadResponseSchema, {
        session,
      }),
    approveWithDemo: (session, key, approvalRequestId) =>
      request(
        "post",
        `api/approval-requests/${approvalRequestId}/approve`,
        ApprovalDecisionResponseSchema,
        { session, key: withKey(key) },
        emptyBody(),
      ),
    rejectWithDemo: (session, key, approvalRequestId) =>
      request(
        "post",
        `api/approval-requests/${approvalRequestId}/reject`,
        ApprovalDecisionResponseSchema,
        { session, key: withKey(key) },
        emptyBody(),
      ),
    approveWithJwt: (jwt, key, approvalRequestId) =>
      request(
        "post",
        `api/approval-requests/${approvalRequestId}/approve`,
        ApprovalDecisionResponseSchema,
        { jwt: JwtTokenSchema.parse(jwt), key: withKey(key) },
        emptyBody(),
      ),
    rejectWithJwt: (jwt, key, approvalRequestId) =>
      request(
        "post",
        `api/approval-requests/${approvalRequestId}/reject`,
        ApprovalDecisionResponseSchema,
        { jwt: JwtTokenSchema.parse(jwt), key: withKey(key) },
        emptyBody(),
      ),
    getRunEvidence,
    runBenchmark: (session, key, input) =>
      request(
        "post",
        "api/benchmarks",
        BenchmarkResponseSchema,
        { session, key: withKey(key) },
        BenchmarkRequestSchema.parse(input),
      ),
    streamRunEvents: runEvents,
  }
}
