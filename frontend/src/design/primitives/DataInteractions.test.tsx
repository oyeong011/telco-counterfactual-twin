import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { useState } from "react"
import { describe, expect, it } from "vitest"
import { EventTimeline, type TimelineEvent } from "./EventTimeline"
import { MetricDelta, type MetricDeltaRow, type MetricSeries } from "./MetricDelta"
import { TopologyCanvas, type TopologyEdge, type TopologyNode } from "./TopologyCanvas"
import { type PatchLine, TypedPatchDiff } from "./TypedPatchDiff"

const NODES = [
  { id: "core", label: "Core DC", x: 50, y: 16, status: "approved" },
  { id: "site-c", label: "Site C", x: 82, y: 78, status: "rejected" },
] as const satisfies readonly TopologyNode[]

const EDGES = [
  {
    id: "core-site-c",
    sourceId: "core",
    targetId: "site-c",
    linkType: "backhaul",
    status: "rejected",
    impact: "high",
    evidenceId: "fixture-evidence-7f3d",
  },
] as const satisfies readonly TopologyEdge[]

const EVENTS = [
  {
    id: "event-started",
    timestamp: "+00:00:01.234",
    type: "Synthetic scenario started",
    impacted: "GLOBAL",
    severity: "info",
    evidenceId: "fixture-evidence-7f3a",
  },
  {
    id: "event-policy",
    timestamp: "+00:00:47.668",
    type: "Policy threshold exceeded",
    impacted: "CORE_DC",
    severity: "critical",
    evidenceId: "fixture-evidence-7f3e",
  },
] as const satisfies readonly TimelineEvent[]

const SERIES = [
  { label: "Baseline", style: "dashed", values: [62, 70, 64] },
  { label: "Candidate", style: "solid", values: [66, 75, 73] },
] as const satisfies readonly MetricSeries[]

const METRICS = [
  {
    id: "throughput",
    metric: "P95 DL throughput",
    baseline: "142.3 Mbps",
    candidate: "167.8 Mbps",
    delta: "+17.9%",
    direction: "improved",
  },
] as const satisfies readonly MetricDeltaRow[]

const LINES = [
  { id: "line-context", number: 129, kind: "context", content: "prb_allocation:" },
  { id: "line-addition", number: 130, kind: "addition", content: "max_prb: 75" },
] as const satisfies readonly PatchLine[]

function TopologyHarness() {
  const [selectedNodeId, setSelectedNodeId] = useState("core")
  const [highlightedNodeId, setHighlightedNodeId] = useState<string>()
  return (
    <TopologyCanvas
      title="Topology snapshot"
      nodes={NODES}
      edges={EDGES}
      selectedNodeId={selectedNodeId}
      {...(highlightedNodeId ? { highlightedNodeId } : {})}
      onSelectNode={setSelectedNodeId}
      onHighlightNode={setHighlightedNodeId}
    />
  )
}

function TimelineHarness() {
  const [selectedEventId, setSelectedEventId] = useState("event-started")
  return (
    <EventTimeline
      title="Simulation trace"
      events={EVENTS}
      selectedEventId={selectedEventId}
      onSelectEvent={setSelectedEventId}
    />
  )
}

function MetricHarness() {
  const [selectedMetricId, setSelectedMetricId] = useState("throughput")
  return (
    <MetricDelta
      title="Metric deltas"
      series={SERIES}
      rows={METRICS}
      selectedMetricId={selectedMetricId}
      onSelectMetric={setSelectedMetricId}
    />
  )
}

function PatchHarness() {
  const [selectedLineId, setSelectedLineId] = useState("line-context")
  return (
    <TypedPatchDiff
      path="configs/site-c/scheduler.yaml"
      schemaVersion="twin.patch.v1"
      validationSummary="Evidence only"
      lines={LINES}
      selectedLineId={selectedLineId}
      onSelectLine={setSelectedLineId}
    />
  )
}

describe("interactive data primitives", () => {
  it("selects and highlights a topology node through real controls", async () => {
    // Given
    const user = userEvent.setup()
    render(<TopologyHarness />)
    const site = screen.getByRole("option", { name: "Site C, rejected" })

    // When
    await user.hover(site)

    // Then
    expect(screen.getByText("Highlighted node: Site C")).toBeVisible()

    // When
    await user.click(site)

    // Then
    expect(site).toHaveAttribute("aria-selected", "true")
    expect(screen.getByText("Selected node: Site C")).toBeVisible()
    expect(site).toHaveFocus()
  })

  it("changes the selected timeline event after a user click", async () => {
    // Given
    const user = userEvent.setup()
    render(<TimelineHarness />)
    const event = screen.getByRole("button", { name: "Select event Policy threshold exceeded" })

    // When
    await user.click(event)

    // Then
    expect(event).toHaveAttribute("aria-pressed", "true")
    expect(event).toHaveFocus()
  })

  it("changes the selected metric after a user click", async () => {
    // Given
    const user = userEvent.setup()
    render(<MetricHarness />)
    const metric = screen.getByRole("button", { name: "Select metric P95 DL throughput" })

    // When
    await user.click(metric)

    // Then
    expect(metric).toHaveAttribute("aria-pressed", "true")
    expect(metric).toHaveFocus()
  })

  it("changes the selected patch line after a user click", async () => {
    // Given
    const user = userEvent.setup()
    render(<PatchHarness />)
    const line = screen.getByRole("button", { name: "Select line 130 Addition" })

    // When
    await user.click(line)

    // Then
    expect(line).toHaveAttribute("aria-pressed", "true")
    expect(line).toHaveFocus()
  })
})
