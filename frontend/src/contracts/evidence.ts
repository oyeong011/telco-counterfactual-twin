import { z } from "zod"
import { ApprovalProofSchema as ProofSchema } from "./approval"
import {
  ContractIdSchema,
  GitCommitShaSchema,
  SafeKeySchema,
  SafePropertiesSchema,
  SchemaVersionSchema,
  Sha256HexSchema,
  UtcTimestampSchema,
  VersionedExtensionsSchema,
} from "./primitives"

const strictObject = <T extends z.ZodRawShape>(shape: T) => z.object(shape).strict()
const nullableExtensions = VersionedExtensionsSchema.nullable().optional()

export const EventSchema = strictObject({
  schema_version: SchemaVersionSchema,
  event_id: ContractIdSchema,
  scenario_id: ContractIdSchema,
  timestamp: UtcTimestampSchema,
  priority: z.number().int().min(-1000).max(1000),
  sequence_id: z
    .number()
    .int()
    .min(0)
    .max(2 ** 53 - 1),
  event_type: SafeKeySchema,
  payload: SafePropertiesSchema,
  extensions: nullableExtensions,
})
export type Event = z.infer<typeof EventSchema>

export const EvidenceCardSchema = strictObject({
  schema_version: SchemaVersionSchema,
  evidence_id: ContractIdSchema,
  session_id: ContractIdSchema,
  scenario_hash: Sha256HexSchema,
  patch_hash: Sha256HexSchema,
  simulation_hash: Sha256HexSchema,
  policy_hash: Sha256HexSchema,
  approval_proof_hash: Sha256HexSchema.nullable(),
  seed: z
    .number()
    .int()
    .min(0)
    .max(2 ** 53 - 1),
  source_commit_sha: GitCommitShaSchema,
  contract_hashes: z
    .record(SafeKeySchema, Sha256HexSchema)
    .refine((value) => Object.keys(value).length >= 1 && Object.keys(value).length <= 32),
  generated_at: UtcTimestampSchema,
  extensions: nullableExtensions,
})
export type EvidenceCard = z.infer<typeof EvidenceCardSchema>

export const EvidenceResponseSchema = strictObject({
  run_id: ContractIdSchema,
  evidence_card: EvidenceCardSchema,
  events: z.array(EventSchema),
  approval_proof: ProofSchema.nullable(),
})
export type EvidenceResponse = z.infer<typeof EvidenceResponseSchema>

export const EmptyRequestSchema = z.object({}).strict()
export type EmptyRequest = z.infer<typeof EmptyRequestSchema>
