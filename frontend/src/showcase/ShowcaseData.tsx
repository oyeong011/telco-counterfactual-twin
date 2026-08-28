import { EventTimeline } from "../design/primitives/EventTimeline"
import { MetricDelta } from "../design/primitives/MetricDelta"
import { TopologyCanvas } from "../design/primitives/TopologyCanvas"
import { TypedPatchDiff } from "../design/primitives/TypedPatchDiff"
import {
  METRIC_ROWS,
  METRIC_SERIES,
  PATCH_LINES,
  TIMELINE_EVENTS,
  TOPOLOGY_EDGES,
  TOPOLOGY_NODES,
} from "./showcaseFixtures"

export function ShowcaseData() {
  return (
    <div className="showcaseStack">
      <section id="topology">
        <TopologyCanvas
          title="Synthetic core topology"
          nodes={TOPOLOGY_NODES}
          edges={TOPOLOGY_EDGES}
          state="demo"
        />
      </section>
      <div className="showcaseGrid showcaseGridWide">
        <section id="metrics">
          <MetricDelta
            title="Baseline versus candidate"
            series={METRIC_SERIES}
            rows={METRIC_ROWS}
            state="approved"
          />
        </section>
        <section id="timeline">
          <EventTimeline title="Simulation trace" events={TIMELINE_EVENTS} state="demo" />
        </section>
      </div>
      <TypedPatchDiff
        path="configs/gnb/site-c/scheduler.yaml"
        schemaVersion="twin.patch.v1"
        state="rejected"
        validationSummary="Rejected by freshness policy. No execution authority exists."
        lines={PATCH_LINES}
      />
    </div>
  )
}
