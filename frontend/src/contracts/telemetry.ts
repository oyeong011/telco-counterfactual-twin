import { z } from "zod"
import {
  ContractIdSchema,
  ObservationQualitySchema,
  SafeKeySchema,
  SchemaVersionSchema,
  UtcTimestampSchema,
  VersionedExtensionsSchema,
} from "./primitives"

const strictObject = <T extends z.ZodRawShape>(shape: T) => z.object(shape).strict()

export const MetricSampleSchema = strictObject({
  metric_name: SafeKeySchema,
  target_id: ContractIdSchema,
  value: z.number().finite().min(-1_000_000_000).max(1_000_000_000),
  unit: SafeKeySchema,
  observed_at: UtcTimestampSchema,
  quality: ObservationQualitySchema,
})
export type MetricSample = z.infer<typeof MetricSampleSchema>

export const TelemetrySchema = strictObject({
  schema_version: SchemaVersionSchema,
  telemetry_id: ContractIdSchema,
  topology_id: ContractIdSchema,
  samples: z.array(MetricSampleSchema).min(1).max(1024),
  extensions: VersionedExtensionsSchema.nullable().optional(),
})
export type Telemetry = z.infer<typeof TelemetrySchema>
