import type { Options } from "ky"
import type {
  ApiFailure,
  ApiResult,
  ApprovalDecisionResponse,
  ApprovalReadResponse,
  ApprovalRequestResponse,
  BenchmarkRequest,
  BenchmarkResponse,
  ComparisonResponse,
  ContractId,
  DemoSessionResponse,
  DiagnosisResponse,
  EvidenceResponse,
  HealthResponse,
  PatchResponse,
  ReadyResponse,
  RootDescriptor,
  ScenarioCreateRequest,
  ScenarioListResponse,
  ScenarioResponse,
  ServiceBuildInfo,
  SimulationReadResponse,
  SimulationResponse,
  TypedPatch,
} from "../contracts/generated"
import type { JwtToken, SessionAuth } from "./auth"
import type { IdempotencyKey } from "./idempotency"
import type { SseFrame } from "./sse"

export type ApiClientOptions = {
  readonly baseUrl?: string
  readonly fetch?: Options["fetch"]
}

export type ApiClient = {
  readonly baseUrl: string
  readonly timeoutMs: number
  readonly bootstrapDemoSession: () => Promise<ApiResult<DemoSessionResponse>>
  readonly getHealth: () => Promise<ApiResult<HealthResponse>>
  readonly getReadiness: () => Promise<ApiResult<ReadyResponse>>
  readonly getBuildInfo: () => Promise<ApiResult<ServiceBuildInfo>>
  readonly getApprovalRoot: () => Promise<ApiResult<RootDescriptor>>
  readonly listScenarios: (session: SessionAuth) => Promise<ApiResult<ScenarioListResponse>>
  readonly createScenario: (
    session: SessionAuth,
    key: IdempotencyKey,
    input: ScenarioCreateRequest,
  ) => Promise<ApiResult<ScenarioResponse>>
  readonly getScenario: (
    session: SessionAuth,
    scenarioId: ContractId,
  ) => Promise<ApiResult<ScenarioResponse>>
  readonly diagnoseScenario: (
    session: SessionAuth,
    key: IdempotencyKey,
    scenarioId: ContractId,
  ) => Promise<ApiResult<DiagnosisResponse>>
  readonly proposePatch: (
    session: SessionAuth,
    key: IdempotencyKey,
    scenarioId: ContractId,
    patch: TypedPatch,
  ) => Promise<ApiResult<PatchResponse>>
  readonly createSimulation: (
    session: SessionAuth,
    key: IdempotencyKey,
    patchId: ContractId,
  ) => Promise<ApiResult<SimulationResponse>>
  readonly getSimulation: (
    session: SessionAuth,
    simulationId: ContractId,
  ) => Promise<ApiResult<SimulationReadResponse>>
  readonly compareSimulation: (
    session: SessionAuth,
    key: IdempotencyKey,
    simulationId: ContractId,
  ) => Promise<ApiResult<ComparisonResponse>>
  readonly requestApproval: (
    session: SessionAuth,
    key: IdempotencyKey,
    simulationId: ContractId,
  ) => Promise<ApiResult<ApprovalRequestResponse>>
  readonly getApprovalRequest: (
    session: SessionAuth,
    approvalRequestId: ContractId,
  ) => Promise<ApiResult<ApprovalReadResponse>>
  readonly approveWithDemo: (
    session: SessionAuth,
    key: IdempotencyKey,
    approvalRequestId: ContractId,
  ) => Promise<ApiResult<ApprovalDecisionResponse>>
  readonly rejectWithDemo: (
    session: SessionAuth,
    key: IdempotencyKey,
    approvalRequestId: ContractId,
  ) => Promise<ApiResult<ApprovalDecisionResponse>>
  readonly approveWithJwt: (
    jwt: JwtToken,
    key: IdempotencyKey,
    approvalRequestId: ContractId,
  ) => Promise<ApiResult<ApprovalDecisionResponse>>
  readonly rejectWithJwt: (
    jwt: JwtToken,
    key: IdempotencyKey,
    approvalRequestId: ContractId,
  ) => Promise<ApiResult<ApprovalDecisionResponse>>
  readonly getRunEvidence: (
    session: SessionAuth,
    runId: ContractId,
  ) => Promise<ApiResult<EvidenceResponse>>
  readonly runBenchmark: (
    session: SessionAuth,
    key: IdempotencyKey,
    input: BenchmarkRequest,
  ) => Promise<ApiResult<BenchmarkResponse>>
  readonly streamRunEvents: (
    session: SessionAuth,
    runId: ContractId,
    lastEventId?: ContractId,
    signal?: AbortSignal,
  ) => AsyncGenerator<SseFrame | ApiFailure>
}
