import { describe, expect, it } from "vitest"
import { EventSchema } from "../contracts/generated"
import { deriveLifecycleResourceGraph } from "./workflow-graph"

const event = (eventId: string, sequenceId: number, resourceId: string) =>
  EventSchema.parse({
    schema_version: "1.0",
    event_id: eventId,
    scenario_id: "scenario-001",
    timestamp: `2026-08-28T00:00:0${sequenceId}Z`,
    priority: 0,
    sequence_id: sequenceId,
    event_type: sequenceId === 0 ? "scenario-created" : "scenario-diagnosed",
    payload: { resource_id: resourceId, run_id: "run-001", status: "recorded" },
  })

describe("truthful lifecycle resource projection", () => {
  it("projects only observed resource order and declares topology unavailable", () => {
    // Given: backend-shaped events containing resource identities but no topology links.
    const events = [event("event-001", 0, "scenario-001"), event("event-002", 1, "diagnosis-001")]

    // When: the lifecycle projection is derived.
    const graph = deriveLifecycleResourceGraph(events)

    // Then: the graph is explicitly non-topological and its edge means observed sequence only.
    expect(graph.kind).toBe("lifecycle-resource-graph")
    expect(graph.topology).toEqual({
      kind: "unavailable",
      reason: "no-http-topology-read-contract",
    })
    expect(graph.nodes.map((node) => node.id)).toEqual(["scenario-001", "diagnosis-001"])
    expect(graph.edges).toEqual([
      {
        id: "event-002",
        sourceId: "scenario-001",
        targetId: "diagnosis-001",
        relation: "observed-next",
      },
    ])
  })

  it("drops malformed and repeated resource identifiers without inventing nodes", () => {
    // Given: one valid observation, a repeated resource, and one malformed resource string.
    const events = [
      event("event-001", 0, "scenario-001"),
      event("event-002", 1, "scenario-001"),
      event("event-003", 2, "not valid"),
    ]

    // When: the projection is derived.
    const graph = deriveLifecycleResourceGraph(events)

    // Then: no self-edge, placeholder, or network-topology fact is fabricated.
    expect(graph.nodes.map((node) => node.id)).toEqual(["scenario-001"])
    expect(graph.edges).toEqual([])
  })
})
