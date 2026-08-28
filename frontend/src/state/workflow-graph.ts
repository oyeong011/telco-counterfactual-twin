import { ContractIdSchema, type Event } from "../contracts/generated"
import type { TopologyGraph, TopologyGraphEdge, TopologyGraphNode } from "./workflow-types"

function payloadId(event: Event, key: string): string | null {
  const entry = Object.entries(event.payload).find(([payloadKey]) => payloadKey === key)
  return typeof entry?.[1] === "string" ? entry[1] : null
}

function parsedId(value: string | null) {
  if (value === null) return null
  const parsed = ContractIdSchema.safeParse(value)
  return parsed.success ? parsed.data : null
}

export function deriveTopologyGraph(events: readonly Event[]): TopologyGraph {
  const nodes = new Map<string, TopologyGraphNode>()
  const edges: TopologyGraphEdge[] = []
  for (const event of events) {
    nodes.set(event.scenario_id, { id: event.scenario_id })
    const resource = parsedId(payloadId(event, "resource_id"))
    if (resource) nodes.set(resource, { id: resource })
    const source = parsedId(payloadId(event, "source_id"))
    const target = parsedId(payloadId(event, "target_id"))
    const link = parsedId(payloadId(event, "link_id"))
    if (source && target && link) {
      nodes.set(source, { id: source })
      nodes.set(target, { id: target })
      edges.push({ id: link, sourceId: source, targetId: target })
    }
  }
  return { nodes: [...nodes.values()], edges }
}
