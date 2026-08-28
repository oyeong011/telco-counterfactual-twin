import { z } from "zod"
import {
  ContractIdSchema,
  NodeKindSchema,
  SafePropertiesSchema,
  SchemaVersionSchema,
  UtcTimestampSchema,
  VersionedExtensionsSchema,
} from "./primitives"

const strictObject = <T extends z.ZodRawShape>(shape: T) => z.object(shape).strict()

export const TopologyNodeSchema = strictObject({
  node_id: ContractIdSchema,
  kind: NodeKindSchema,
  attributes: SafePropertiesSchema.optional(),
})
export type TopologyNode = z.infer<typeof TopologyNodeSchema>

export const TopologyLinkSchema = strictObject({
  link_id: ContractIdSchema,
  source_id: ContractIdSchema,
  target_id: ContractIdSchema,
  capacity_mbps: z.number().finite().gt(0).max(1_000_000),
  latency_ms: z.number().finite().min(0).max(60_000),
})
export type TopologyLink = z.infer<typeof TopologyLinkSchema>

export const ConfigRecordSchema = strictObject({
  config_version: ContractIdSchema,
  recorded_at: UtcTimestampSchema,
  changes: SafePropertiesSchema,
})
export type ConfigRecord = z.infer<typeof ConfigRecordSchema>

export const TopologySchema = strictObject({
  schema_version: SchemaVersionSchema,
  topology_id: ContractIdSchema,
  seed: z
    .number()
    .int()
    .min(0)
    .max(2 ** 53 - 1),
  nodes: z.array(TopologyNodeSchema).min(9).max(64),
  links: z.array(TopologyLinkSchema).min(1).max(128),
  config_history: z.array(ConfigRecordSchema).min(1).max(128),
  extensions: VersionedExtensionsSchema.nullable().optional(),
}).superRefine((value, context) => {
  const nodeIds = value.nodes.map((node) => node.node_id)
  const linkIds = value.links.map((link) => link.link_id)
  if (new Set(nodeIds).size !== nodeIds.length)
    context.addIssue({ code: "custom", message: "topology node identifiers must be unique" })
  if (new Set(linkIds).size !== linkIds.length)
    context.addIssue({ code: "custom", message: "topology link identifiers must be unique" })
  const cellCount = value.nodes.filter((node) => node.kind === "cell").length
  if (cellCount < 2 || cellCount > 4)
    context.addIssue({ code: "custom", message: "topology requires two to four cells" })
  const kinds = new Set(value.nodes.map((node) => node.kind))
  if (kinds.size !== 8)
    context.addIssue({ code: "custom", message: "topology node family is missing" })
  const known = new Set(nodeIds)
  for (const link of value.links) {
    if (!known.has(link.source_id) || !known.has(link.target_id))
      context.addIssue({ code: "custom", message: "topology link endpoint is unknown" })
  }
})
export type Topology = z.infer<typeof TopologySchema>
