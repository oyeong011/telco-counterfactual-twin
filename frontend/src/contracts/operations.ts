import { z } from "zod"
import { SessionKeyCertificateSchema } from "./domain"
import {
  ContractIdSchema,
  DigestScopeSchema,
  GitCommitShaSchema,
  SafeKeySchema,
  SchemaVersionSchema,
  SemanticVersionSchema,
  Sha256HexSchema,
  UtcTimestampSchema,
  VersionedExtensionsSchema,
} from "./primitives"

const strictObject = <T extends z.ZodRawShape>(shape: T) => z.object(shape).strict()

export const DemoSessionRequestSchema = strictObject({
  synthetic_only: z.literal(true),
})
export type DemoSessionRequest = z.infer<typeof DemoSessionRequestSchema>

export const DemoSessionResponseSchema = strictObject({
  session_id: ContractIdSchema,
  demo_token: z.string().min(1),
  session_certificate: SessionKeyCertificateSchema,
  expires_at: UtcTimestampSchema,
  startup_epoch: ContractIdSchema,
  durability: z.literal("process-memory"),
  synthetic_only: z.literal(true),
})
export type DemoSessionResponse = z.infer<typeof DemoSessionResponseSchema>

export const BenchmarkRequestSchema = strictObject({
  seed: z
    .number()
    .int()
    .min(0)
    .max(2 ** 53 - 1),
  iterations: z.number().int().min(2).max(25),
})
export type BenchmarkRequest = z.infer<typeof BenchmarkRequestSchema>

export const BenchmarkResponseSchema = strictObject({
  seed: z
    .number()
    .int()
    .min(0)
    .max(2 ** 53 - 1),
  iterations: z.number().int(),
  unique_trace_hashes: z.number().int().min(0),
  deterministic: z.boolean(),
  trace_hash: Sha256HexSchema,
})
export type BenchmarkResponse = z.infer<typeof BenchmarkResponseSchema>

export const HealthResponseSchema = strictObject({
  status: z.literal("live"),
})
export type HealthResponse = z.infer<typeof HealthResponseSchema>

export const ReadyResponseSchema = strictObject({
  status: z.enum(["ready", "degraded"]),
  checks: z.record(z.string().min(1), z.boolean()),
})
export type ReadyResponse = z.infer<typeof ReadyResponseSchema>

export const ServiceBuildInfoSchema = strictObject({
  schema_version: SchemaVersionSchema,
  service_name: ContractIdSchema,
  version: SemanticVersionSchema,
  runtime_source_commit_sha: GitCommitShaSchema,
  release_commit_sha: GitCommitShaSchema,
  runtime_tree_hash: Sha256HexSchema,
  schema_hashes: z
    .record(SafeKeySchema, Sha256HexSchema)
    .refine((value) => Object.keys(value).length >= 1 && Object.keys(value).length <= 64),
  mcp_hash: Sha256HexSchema,
  policy_hash: Sha256HexSchema,
  trusted_root_hashes: Sha256HexSchema,
  built_at: UtcTimestampSchema,
  image_digest: z.string().regex(/^sha256:[0-9a-f]{64}$/),
  digest_scope: DigestScopeSchema,
  extensions: VersionedExtensionsSchema.nullable().optional(),
})
export type ServiceBuildInfo = z.infer<typeof ServiceBuildInfoSchema>

export const UiBuildInfoSchema = strictObject({
  schema_version: SchemaVersionSchema,
  service_name: ContractIdSchema,
  version: SemanticVersionSchema,
  runtime_source_commit_sha: GitCommitShaSchema,
  release_commit_sha: GitCommitShaSchema,
  runtime_tree_hash: Sha256HexSchema,
  schema_hashes: z
    .record(SafeKeySchema, Sha256HexSchema)
    .refine((value) => Object.keys(value).length >= 1 && Object.keys(value).length <= 64),
  mcp_hash: Sha256HexSchema,
  policy_hash: Sha256HexSchema,
  trusted_root_hashes: Sha256HexSchema,
  built_at: UtcTimestampSchema,
  asset_manifest_hash: Sha256HexSchema,
  extensions: VersionedExtensionsSchema.nullable().optional(),
})
export type UiBuildInfo = z.infer<typeof UiBuildInfoSchema>

export const PROBLEM_CODES = [
  "origin_required",
  "origin_forbidden",
  "bootstrap_rate_limited",
  "content_length_required",
  "content_length_invalid",
  "bootstrap_body_too_large",
  "demo_session_capacity",
  "demo_session_exists",
  "state_store_unavailable",
  "approval_root_invalid",
  "demo_token_required",
  "demo_token_invalid",
  "demo_token_expired",
  "demo_session_lost",
  "demo_session_not_found",
  "session_state_unavailable",
  "idempotency_key_required",
  "idempotency_key_invalid",
  "idempotency_conflict",
  "scenario_not_found",
  "patch_not_found",
  "simulation_not_found",
  "approval_request_not_found",
  "approval_state_unavailable",
  "run_not_found",
  "comparison_required",
  "evidence_incomplete",
  "approval_already_terminal",
  "approval_window_expired",
  "request_validation_failed",
  "policy_ineligible",
  "policy_provenance_required",
  "policy_provenance_unavailable",
  "sse_replay_gap",
  "sse_cursor_wrong_stream",
  "approval_auth_required",
  "jwt_approver_disabled",
  "approver_role_required",
  "jwt_approver_invalid",
  "jwt_config_incomplete",
  "jwt_jwks_invalid",
  "demo_event_capacity",
  "patch_exists",
  "route_not_found",
  "method_not_allowed",
  "client_transport_error",
  "client_timeout_error",
  "client_network_error",
  "client_request_aborted",
  "client_contract_error",
] as const
export const ProblemCodeSchema = z.enum(PROBLEM_CODES)
export type ProblemCode = z.infer<typeof ProblemCodeSchema>

export const ProblemDetailsSchema = strictObject({
  type: z.string().startsWith("https://telco-twin.invalid/problems/"),
  title: z.string().min(1),
  status: z.number().int().min(400).max(599),
  code: ProblemCodeSchema,
  detail: z.string().min(1),
  request_id: z.string().min(1),
})
export type ProblemDetails = z.infer<typeof ProblemDetailsSchema>

export const ApiMetaSchema = strictObject({
  requestId: z.string().min(1),
  replayed: z.boolean(),
})
export type ApiMeta = z.infer<typeof ApiMetaSchema>

export type ApiSuccess<T> = {
  readonly ok: true
  readonly data: T
  readonly meta: ApiMeta
}

export type ApiFailure = {
  readonly ok: false
  readonly problem: ProblemDetails
  readonly requestId: string
}

export type ApiResult<T> = ApiSuccess<T> | ApiFailure
