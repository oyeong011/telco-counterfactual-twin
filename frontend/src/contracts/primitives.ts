import { z } from "zod"

export const ID_PATTERN = /^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$/
export const SAFE_KEY_PATTERN =
  /^(?!(?:email|gpsi|imei|imsi|msisdn|phone|subscriber[-_]?id|supi|apply[-_]?to[-_]?network|command|execute|execution|push[-_]?config|revoke|revocation|shell|url)$)[a-z][a-z0-9]*(?:[-_][a-z0-9]+)*$/
export const UTC_PATTERN = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/
export const SHA256_PATTERN = /^[0-9a-f]{64}$/
export const GIT_SHA_PATTERN = /^[0-9a-f]{40}$/
export const SEMVER_PATTERN = /^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?$/
export const BASE64URL_PATTERN = /^[A-Za-z0-9_-]+$/
const SAFE_EXACT_KEYS = new Set([
  "commandment_count",
  "config_history",
  "curiosity_score",
  "duration_ms",
  "executioner_state",
  "flourish_count",
  "jurisdiction_code",
  "maturity_score",
  "purity_index",
  "security_level",
  "shellfish_count",
  "tokenization_mode",
  "ue_cohort_id",
])

function semanticallySafeKey(value: string): boolean {
  if (SAFE_EXACT_KEYS.has(value)) return true
  const normalized = value.replace(/[-_]/g, "")
  const parts = value.split(/[-_]/)
  const has = (values: readonly string[]) => parts.some((part) => values.includes(part))
  const directPii = [
    "customer",
    "email",
    "gpsi",
    "imei",
    "imsi",
    "msisdn",
    "phone",
    "subscriber",
    "supi",
  ].some((stem) => normalized.includes(stem))
  const directAuthority = [
    "command",
    "execute",
    "execution",
    "revoke",
    "revocation",
    "shell",
    "url",
    "uri",
  ].some((stem) => normalized.includes(stem))
  const directSecret = ["credential", "passwd", "password", "secret", "token"].some((stem) =>
    normalized.includes(stem),
  )
  const apiSecret =
    parts.includes("api") && has(["key", "secret", "token"]) && !normalized.includes("rapid")
  const pii =
    has(["customer", "subscriber"]) && has(["id", "identifier", "identifiers", "identity"])
  const authority =
    (has(["push"]) && has(["config", "network", "payload"])) ||
    (has(["apply"]) && has(["config", "network", "payload"])) ||
    (has(["shell"]) && has(["command"])) ||
    (has(["arbitrary"]) && has(["uri", "url"])) ||
    (has(["execute", "execution"]) &&
      has(["action", "command", "network", "operation", "payload", "plan", "request"])) ||
    (has(["command"]) && has(["action", "network", "operation", "payload", "plan", "request"])) ||
    (has(["revoke", "revocation"]) && has(["id", "identifier", "reason", "status", "token"]))
  const secret = has(["credential", "passwd", "password", "secret", "token"])
  const accessSecret = has(["access"]) && has(["key", "secret", "token"])
  return !(
    directPii ||
    directAuthority ||
    directSecret ||
    apiSecret ||
    pii ||
    authority ||
    secret ||
    accessSecret
  )
}

export const SchemaVersionSchema = z.literal("1.0")
export type SchemaVersion = z.infer<typeof SchemaVersionSchema>

export const ContractIdSchema = z.string().min(3).max(96).regex(ID_PATTERN).brand<"ContractId">()
export type ContractId = z.infer<typeof ContractIdSchema>

export const Sha256HexSchema = z.string().regex(SHA256_PATTERN).brand<"Sha256Hex">()
export type Sha256Hex = z.infer<typeof Sha256HexSchema>

export const GitCommitShaSchema = z.string().regex(GIT_SHA_PATTERN).brand<"GitCommitSha">()
export type GitCommitSha = z.infer<typeof GitCommitShaSchema>

export const UtcTimestampSchema = z
  .string()
  .regex(UTC_PATTERN)
  .refine((value) => {
    const parsed = Date.parse(value)
    return !Number.isNaN(parsed) && new Date(parsed).toISOString() === `${value.slice(0, -1)}.000Z`
  })
  .brand<"UtcTimestamp">()
export type UtcTimestamp = z.infer<typeof UtcTimestampSchema>

export const SemanticVersionSchema = z.string().regex(SEMVER_PATTERN).brand<"SemanticVersion">()
export type SemanticVersion = z.infer<typeof SemanticVersionSchema>

export const SafeKeySchema = z
  .string()
  .min(1)
  .max(64)
  .regex(SAFE_KEY_PATTERN)
  .refine(semanticallySafeKey)
  .brand<"SafeKey">()
export type SafeKey = z.infer<typeof SafeKeySchema>

export const JsonScalarSchema = z.union([
  z.string(),
  z
    .number()
    .int()
    .min(-(2 ** 53) + 1)
    .max(2 ** 53 - 1),
  z
    .number()
    .finite()
    .min(-(2 ** 53) + 1)
    .max(2 ** 53 - 1),
  z.boolean(),
  z.null(),
])
export type JsonScalar = z.infer<typeof JsonScalarSchema>

export const SafePropertiesSchema = z
  .record(SafeKeySchema, JsonScalarSchema)
  .refine((value) => Object.keys(value).length <= 32)
export type SafeProperties = z.infer<typeof SafePropertiesSchema>

export const VersionedExtensionsSchema = z
  .object({
    schema_version: SchemaVersionSchema,
    values: SafePropertiesSchema.optional(),
  })
  .strict()
export type VersionedExtensions = z.infer<typeof VersionedExtensionsSchema>

export const FaultFamilyValues = [
  "radio-congestion",
  "backhaul-degradation",
  "upf-saturation",
  "neighbor-handover-misconfiguration",
  "slice-scheduler-misallocation",
  "alarm-prompt-injection",
] as const
export const FaultFamilySchema = z.enum(FaultFamilyValues)
export type FaultFamily = z.infer<typeof FaultFamilySchema>

export const DiagnosisStatusValues = ["no-fault", "primary", "ambiguous"] as const
export const DiagnosisStatusSchema = z.enum(DiagnosisStatusValues)
export type DiagnosisStatus = z.infer<typeof DiagnosisStatusSchema>

export const TargetKindValues = [
  "cell",
  "backhaul",
  "upf",
  "neighbor-relation",
  "slice",
  "alarm",
] as const
export const TargetKindSchema = z.enum(TargetKindValues)
export type TargetKind = z.infer<typeof TargetKindSchema>

export const PatchOperationValues = [
  "adjust-radio-capacity",
  "restore-backhaul-capacity",
  "scale-upf-capacity",
  "correct-neighbor-relation",
  "rebalance-slice-weight",
  "ignore-untrusted-alarm",
] as const
export const PatchOperationSchema = z.enum(PatchOperationValues)
export type PatchOperation = z.infer<typeof PatchOperationSchema>

export const ApprovalEvidenceStateValues = ["pending", "approved", "rejected"] as const
export const ApprovalEvidenceStateSchema = z.enum(ApprovalEvidenceStateValues)
export type ApprovalEvidenceState = z.infer<typeof ApprovalEvidenceStateSchema>

export const ApprovalDecisionValues = ["approved", "rejected"] as const
export const ApprovalDecisionSchema = z.enum(ApprovalDecisionValues)
export type ApprovalDecision = z.infer<typeof ApprovalDecisionSchema>

export const PolicyReasonValues = [
  "observation-stale",
  "observation-future",
  "observation-noisy",
  "observation-binding-invalid",
  "unsafe-constraint",
  "patch-hash-missing",
  "simulation-missing",
  "simulation-hash-missing",
  "simulation-provenance-invalid",
] as const
export const PolicyReasonSchema = z.enum(PolicyReasonValues)
export type PolicyReason = z.infer<typeof PolicyReasonSchema>

export const DigestScopeValues = ["local", "registry_manifest"] as const
export const DigestScopeSchema = z.enum(DigestScopeValues)
export type DigestScope = z.infer<typeof DigestScopeSchema>

export const EnvironmentValues = ["test", "production"] as const
export const EnvironmentSchema = z.enum(EnvironmentValues)
export type Environment = z.infer<typeof EnvironmentSchema>

export const EventTypeValues = [
  "scenario-created",
  "scenario-diagnosed",
  "patch-proposed",
  "simulation-completed",
  "comparison-created",
  "approval-requested",
  "approval-approved",
  "approval-rejected",
  "benchmark-completed",
] as const
export const EventTypeSchema = z.enum(EventTypeValues)
export type EventType = z.infer<typeof EventTypeSchema>

export const NodeKindValues = [
  "cell",
  "gnb",
  "ue-cohort",
  "backhaul",
  "amf",
  "smf",
  "upf",
  "slice",
] as const
export const NodeKindSchema = z.enum(NodeKindValues)
export type NodeKind = z.infer<typeof NodeKindSchema>

export const ObservationQualityValues = ["fresh", "stale", "noisy"] as const
export const ObservationQualitySchema = z.enum(ObservationQualityValues)
export type ObservationQuality = z.infer<typeof ObservationQualitySchema>
