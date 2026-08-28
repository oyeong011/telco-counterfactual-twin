import { z } from "zod"
import {
  ContractIdSchema,
  FaultFamilySchema,
  PatchOperationSchema,
  SafePropertiesSchema,
  SchemaVersionSchema,
  Sha256HexSchema,
  TargetKindSchema,
  UtcTimestampSchema,
  VersionedExtensionsSchema,
} from "./primitives"

const strictObject = <T extends z.ZodRawShape>(shape: T) => z.object(shape).strict()
const nullableExtensions = VersionedExtensionsSchema.nullable().optional()

export const ScenarioSchema = strictObject({
  schema_version: SchemaVersionSchema,
  scenario_id: ContractIdSchema,
  topology_id: ContractIdSchema,
  seed: z
    .number()
    .int()
    .min(0)
    .max(2 ** 53 - 1),
  fault_family: FaultFamilySchema,
  starts_at: UtcTimestampSchema,
  duration_seconds: z.number().int().min(1).max(3600),
  target_ids: z.array(ContractIdSchema).min(1).max(16),
  parameters: SafePropertiesSchema,
  extensions: nullableExtensions,
})
export type Scenario = z.infer<typeof ScenarioSchema>

export const ScenarioCreateRequestSchema = strictObject({
  fault_family: FaultFamilySchema,
  seed: z
    .number()
    .int()
    .min(0)
    .max(2 ** 53 - 1),
})
export type ScenarioCreateRequest = z.infer<typeof ScenarioCreateRequestSchema>

export const ScenarioResponseSchema = strictObject({
  scenario: ScenarioSchema,
  topology_hash: Sha256HexSchema,
  scenario_hash: Sha256HexSchema,
  run_id: ContractIdSchema,
})
export type ScenarioResponse = z.infer<typeof ScenarioResponseSchema>

export const ScenarioListResponseSchema = strictObject({ items: z.array(ScenarioResponseSchema) })
export type ScenarioListResponse = z.infer<typeof ScenarioListResponseSchema>

export const DiagnosisResponseSchema = strictObject({
  scenario_id: ContractIdSchema,
  run_id: ContractIdSchema,
  status: z.enum(["no-fault", "primary", "ambiguous"]),
  primary_fault: FaultFamilySchema.nullable(),
  secondary_evidence: z.array(FaultFamilySchema),
})
export type DiagnosisResponse = z.infer<typeof DiagnosisResponseSchema>

export const PatchChangeSchema = strictObject({
  target_id: ContractIdSchema,
  target_kind: TargetKindSchema,
  operation: PatchOperationSchema,
  parameters: SafePropertiesSchema,
})
export type PatchChange = z.infer<typeof PatchChangeSchema>

export const BlastRadiusSchema = strictObject({
  max_cells: z.number().int().min(0).max(4),
  max_ue_cohorts: z.number().int().min(0).max(32),
  max_slices: z.number().int().min(0).max(8),
}).superRefine((value, context) => {
  if (value.max_cells + value.max_ue_cohorts + value.max_slices === 0)
    context.addIssue({ code: "custom", message: "blast radius cannot be empty" })
})
export type BlastRadius = z.infer<typeof BlastRadiusSchema>

export const TypedPatchSchema = strictObject({
  schema_version: SchemaVersionSchema,
  patch_id: ContractIdSchema,
  scenario_id: ContractIdSchema,
  base_topology_hash: Sha256HexSchema,
  changes: z.array(PatchChangeSchema).min(1).max(16),
  blast_radius: BlastRadiusSchema,
  proposed_at: UtcTimestampSchema,
  extensions: nullableExtensions,
})
export type TypedPatch = z.infer<typeof TypedPatchSchema>

export const PatchResponseSchema = strictObject({
  patch: TypedPatchSchema,
  patch_hash: Sha256HexSchema,
  run_id: ContractIdSchema,
})
export type PatchResponse = z.infer<typeof PatchResponseSchema>
