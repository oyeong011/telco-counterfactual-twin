import { ContractIdSchema, type Event } from "../contracts/generated"
import type {
  LifecycleResourceGraph,
  LifecycleResourceGraphEdge,
  LifecycleResourceGraphNode,
} from "./workflow-types"

function payloadId(event: Event, key: string): string | null {
  const entry = Object.entries(event.payload).find(([payloadKey]) => payloadKey === key)
  return typeof entry?.[1] === "string" ? entry[1] : null
}

function parsedId(value: string | null) {
  if (value === null) return null
  const parsed = ContractIdSchema.safeParse(value)
  return parsed.success ? parsed.data : null
}

export function deriveLifecycleResourceGraph(events: readonly Event[]): LifecycleResourceGraph {
  const nodes = new Map<string, LifecycleResourceGraphNode>()
  const edges = new Map<string, LifecycleResourceGraphEdge>()
  let previousResource: ReturnType<typeof parsedId> = null
  for (const event of events) {
    const resource = parsedId(payloadId(event, "resource_id"))
    if (resource === null) continue
    if (!nodes.has(resource))
      nodes.set(resource, {
        id: resource,
        eventId: event.event_id,
        eventType: event.event_type,
        sequenceId: event.sequence_id,
      })
    if (previousResource !== null && previousResource !== resource)
      edges.set(event.event_id, {
        id: event.event_id,
        sourceId: previousResource,
        targetId: resource,
        relation: "observed-next",
      })
    previousResource = resource
  }
  return {
    kind: "lifecycle-resource-graph",
    topology: { kind: "unavailable", reason: "no-http-topology-read-contract" },
    nodes: [...nodes.values()],
    edges: [...edges.values()],
  }
}
