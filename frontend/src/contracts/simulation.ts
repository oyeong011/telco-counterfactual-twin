import { z } from "zod"
import {
  ContractIdSchema,
  PolicyReasonSchema,
  SafeKeySchema,
  SchemaVersionSchema,
  Sha256HexSchema,
  UtcTimestampSchema,
  VersionedExtensionsSchema,
} from "./primitives"

const strictObject = <T extends z.ZodRawShape>(shape: T) => z.object(shape).strict()
const nullableExtensions = VersionedExtensionsSchema.nullable().optional()

export const MetricDeltaSchema = strictObject({
  metric_name: SafeKeySchema,
  baseline: z.number().finite().min(-1_000_000_000).max(1_000_000_000),
  candidate: z.number().finite().min(-1_000_000_000).max(1_000_000_000),
  unit: SafeKeySchema,
})
export type MetricDelta = z.infer<typeof MetricDeltaSchema>

export const ConstraintResultSchema = strictObject({
  constraint_code: SafeKeySchema,
  passed: z.boolean(),
  evidence_hash: Sha256HexSchema,
})
export type ConstraintResult = z.infer<typeof ConstraintResultSchema>

export const SimulationResultSchema = strictObject({
  schema_version: SchemaVersionSchema,
  simulation_id: ContractIdSchema,
  scenario_id: ContractIdSchema,
  patch_hash: Sha256HexSchema,
  baseline_hash: Sha256HexSchema,
  candidate_hash: Sha256HexSchema,
  trace_hash: Sha256HexSchema,
  started_at: UtcTimestampSchema,
  completed_at: UtcTimestampSchema,
  metric_deltas: z.array(MetricDeltaSchema).min(1).max(128),
  constraints: z.array(ConstraintResultSchema).min(1).max(64),
  approval_eligible: z.boolean(),
  extensions: nullableExtensions,
}).superRefine((value, context) => {
  if (Date.parse(value.completed_at) < Date.parse(value.started_at))
    context.addIssue({ code: "custom", message: "simulation completion precedes start" })
  if (value.approval_eligible && value.constraints.some((constraint) => !constraint.passed))
    context.addIssue({ code: "custom", message: "failed constraints cannot be eligible" })
})
export type SimulationResult = z.infer<typeof SimulationResultSchema>

export const SimulationResponseSchema = strictObject({
  simulation_id: ContractIdSchema,
  scenario_id: ContractIdSchema,
  patch_id: ContractIdSchema,
  run_id: ContractIdSchema,
  status: z.literal("completed"),
  trace_hash: Sha256HexSchema,
})
export type SimulationResponse = z.infer<typeof SimulationResponseSchema>

export const SimulationReadResponseSchema = strictObject({
  simulation: SimulationResponseSchema,
  result: SimulationResultSchema.nullable(),
})
export type SimulationReadResponse = z.infer<typeof SimulationReadResponseSchema>

export const ComparisonEvidenceHashesSchema = strictObject({
  patch_hash: Sha256HexSchema,
  baseline_manifest_hash: Sha256HexSchema,
  candidate_manifest_hash: Sha256HexSchema,
  baseline_trace_hash: Sha256HexSchema,
  candidate_trace_hash: Sha256HexSchema,
  constraint_set_hash: Sha256HexSchema,
})
export type ComparisonEvidenceHashes = z.infer<typeof ComparisonEvidenceHashesSchema>

export const CounterfactualComparisonSchema = strictObject({
  result: SimulationResultSchema,
  evidence_hashes: ComparisonEvidenceHashesSchema,
})
export type CounterfactualComparison = z.infer<typeof CounterfactualComparisonSchema>

export const ComparisonResponseSchema = strictObject({
  comparison_id: ContractIdSchema,
  run_id: ContractIdSchema,
  comparison: CounterfactualComparisonSchema,
})
export type ComparisonResponse = z.infer<typeof ComparisonResponseSchema>

export const PolicyEvaluationSchema = strictObject({
  eligible: z.boolean(),
  reasons: z.array(PolicyReasonSchema),
  patch_hash: Sha256HexSchema.nullable(),
  simulation_hash: Sha256HexSchema.nullable(),
  quality_hash: Sha256HexSchema,
  policy_definition_hash: Sha256HexSchema,
  policy_hash: Sha256HexSchema,
})
export type PolicyEvaluation = z.infer<typeof PolicyEvaluationSchema>
