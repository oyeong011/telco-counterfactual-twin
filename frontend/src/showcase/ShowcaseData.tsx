import { DataTable, type DataTableColumn } from "../design/primitives/DataTable"
import { EventTimeline } from "../design/primitives/EventTimeline"
import { MetricDelta } from "../design/primitives/MetricDelta"
import { TopologyCanvas } from "../design/primitives/TopologyCanvas"
import { TypedPatchDiff } from "../design/primitives/TypedPatchDiff"
import { type ShowcaseState, surfaceStateFor } from "./primitiveStateRegistry"
import { ShowcaseStateSection } from "./ShowcaseStates"
import {
  METRIC_ROWS,
  METRIC_SERIES,
  PATCH_LINES,
  TIMELINE_EVENTS,
  TOPOLOGY_EDGES,
  TOPOLOGY_NODES,
} from "./showcaseFixtures"

type CompactRow = {
  readonly id: string
  readonly signal: string
  readonly value: string
}

const COMPACT_ROWS = [
  { id: "throughput", signal: "P95 DL throughput", value: "167.8 Mbps" },
  { id: "latency", signal: "P95 latency", value: "21.3 ms" },
] as const satisfies readonly CompactRow[]

const COMPACT_COLUMNS = [
  { id: "signal", header: "Signal", render: (row: CompactRow) => row.signal },
  { id: "value", header: "Value", render: (row: CompactRow) => row.value },
] satisfies readonly DataTableColumn<CompactRow>[]

function TableExample({ state }: { readonly state: ShowcaseState }) {
  return (
    <DataTable
      caption="Metric evidence table"
      columns={COMPACT_COLUMNS}
      rows={COMPACT_ROWS}
      rowKey={(row) => row.id}
      state={surfaceStateFor(state)}
    />
  )
}

function TopologyExample({ state }: { readonly state: ShowcaseState }) {
  return (
    <TopologyCanvas
      title="Topology snapshot"
      nodes={TOPOLOGY_NODES.slice(0, 3)}
      edges={TOPOLOGY_EDGES.slice(0, 2)}
      state={surfaceStateFor(state)}
    />
  )
}

function TimelineExample({ state }: { readonly state: ShowcaseState }) {
  return (
    <EventTimeline
      title="Simulation trace"
      events={TIMELINE_EVENTS.slice(0, 2)}
      state={surfaceStateFor(state)}
    />
  )
}

function MetricExample({ state }: { readonly state: ShowcaseState }) {
  return (
    <MetricDelta
      title="Metric deltas"
      series={METRIC_SERIES}
      rows={METRIC_ROWS}
      state={surfaceStateFor(state)}
    />
  )
}

function PatchExample({ state }: { readonly state: ShowcaseState }) {
  return (
    <TypedPatchDiff
      path="configs/site-c/scheduler.yaml"
      schemaVersion="twin.patch.v1"
      state={surfaceStateFor(state)}
      validationSummary="Evidence-only fixture; no execution authority."
      lines={PATCH_LINES}
    />
  )
}

export function ShowcaseData() {
  return (
    <div className="showcaseStack">
      <ShowcaseStateSection
        primitive="DataTable"
        description="Exact values remain available in a semantic, scroll-labelled table."
      >
        {(state) => <TableExample state={state} />}
      </ShowcaseStateSection>
      <ShowcaseStateSection
        primitive="TopologyCanvas"
        description="The graph stays paired with a keyboard-accessible adjacency fallback."
      >
        {(state) => <TopologyExample state={state} />}
      </ShowcaseStateSection>
      <ShowcaseStateSection
        primitive="EventTimeline"
        description="Ordered events retain severity, impacted scope, timestamps, and evidence links."
      >
        {(state) => <TimelineExample state={state} />}
      </ShowcaseStateSection>
      <ShowcaseStateSection
        primitive="MetricDelta"
        description="Line style and exact-value rows distinguish baseline from candidate evidence."
      >
        {(state) => <MetricExample state={state} />}
      </ShowcaseStateSection>
      <ShowcaseStateSection
        primitive="TypedPatchDiff"
        description="Typed patch lines expose additions, removals, validation, and policy boundaries."
      >
        {(state) => <PatchExample state={state} />}
      </ShowcaseStateSection>
    </div>
  )
}
