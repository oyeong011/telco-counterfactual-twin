import { useConsole } from "../console/ConsoleContext"
import { ApprovalEvidence, type ApprovalStep } from "../design/primitives/ApprovalEvidence"
import { EventTimeline, type TimelineEvent } from "../design/primitives/EventTimeline"
import { MetricDelta, type MetricDeltaRow } from "../design/primitives/MetricDelta"
import { StatusChip } from "../design/primitives/StatusChip"
import { TopologyCanvas } from "../design/primitives/TopologyCanvas"
import { WORKFLOW_PHASES } from "../state/workflow"

const DISPLAYED_PHASES = WORKFLOW_PHASES.filter(
  (phase) => phase !== "bootstrapping" && phase !== "session-error" && phase !== "approval-blocked",
)

export function LifecycleProgress() {
  const { model } = useConsole()
  const activePhase =
    model.workflow.phase === "approval-blocked"
      ? "comparison"
      : model.workflow.phase === "bootstrapping" || model.workflow.phase === "session-error"
        ? "no-session"
        : model.workflow.phase
  const currentIndex = DISPLAYED_PHASES.indexOf(activePhase)
  return (
    <section className="panel lifecyclePanel" aria-labelledby="lifecycle-heading">
      <div className="panelHeader">
        <h2 id="lifecycle-heading">Governed lifecycle</h2>
        <StatusChip tone="info" label={model.workflow.phase} />
      </div>
      <ol className="lifecycleSteps">
        {DISPLAYED_PHASES.map((phase, index) => (
          <li
            key={phase}
            data-state={
              index < currentIndex ? "complete" : index === currentIndex ? "current" : "future"
            }
          >
            <span>{index + 1}</span>
            {phase}
          </li>
        ))}
      </ol>
    </section>
  )
}

export function TopologyContractPanel() {
  const { model } = useConsole()
  const topologyId = model.snapshot.scenario?.scenario.topology_id
  return (
    <div className="topologyContractStack">
      <TopologyCanvas title="Physical topology" nodes={[]} edges={[]} state="empty" />
      <p className="contractGap">
        {topologyId
          ? `Scenario ${topologyId} exposes an identifier and hash, but the HTTP contract has no node or link read endpoint. No physical graph has been fabricated.`
          : "Create a scenario to receive a topology identifier. The console never invents physical nodes or links."}
      </p>
    </div>
  )
}

function eventResourceId(event: ReturnType<typeof useConsole>["model"]["events"][number]): string {
  const value = Object.entries(event.payload).find(([key]) => key === "resource_id")?.[1]
  return typeof value === "string" ? value : "Resource not disclosed"
}

function timelineEvents(
  events: ReturnType<typeof useConsole>["model"]["events"],
): readonly TimelineEvent[] {
  return events.map((event) => ({
    id: event.event_id,
    timestamp: event.timestamp,
    type: event.event_type,
    impacted: eventResourceId(event),
    severity:
      event.event_type === "approval-rejected"
        ? "critical"
        : event.event_type === "approval-requested"
          ? "warning"
          : "info",
    evidenceId: event.event_id,
  }))
}

export function CurrentEventTimeline() {
  const { model, actions } = useConsole()
  return (
    <section className="stackRegion">
      <div className="sectionActions">
        <p>
          SSE is a finite authenticated replay that ends after the current snapshot and heartbeat.
        </p>
        <button
          type="button"
          disabled={model.snapshot.run === undefined || model.busy === "events"}
          onClick={() => void actions.replayEvents()}
        >
          Replay current events
        </button>
      </div>
      <EventTimeline
        title="Recorded event replay"
        events={timelineEvents(model.events)}
        state={
          model.busy === "events" ? "loading" : model.events.length === 0 ? "empty" : "default"
        }
      />
    </section>
  )
}

function metricRows(model: ReturnType<typeof useConsole>["model"]): readonly MetricDeltaRow[] {
  const metrics = model.snapshot.comparison?.comparison.result.metric_deltas ?? []
  return metrics.map((metric) => {
    const delta = metric.candidate - metric.baseline
    return {
      id: metric.metric_name,
      metric: metric.metric_name,
      baseline: `${metric.baseline} ${metric.unit}`,
      candidate: `${metric.candidate} ${metric.unit}`,
      delta: `${delta >= 0 ? "+" : ""}${delta} ${metric.unit}`,
      direction: delta === 0 ? "neutral" : "changed",
    }
  })
}

export function ComparisonPanel() {
  const { model } = useConsole()
  const rows = metricRows(model)
  const values = model.snapshot.comparison?.comparison.result.metric_deltas[0]
  return (
    <MetricDelta
      title="Baseline versus candidate"
      rows={rows}
      series={
        values
          ? [
              { label: "Baseline", style: "dashed", values: [values.baseline, values.baseline] },
              { label: "Candidate", style: "solid", values: [values.baseline, values.candidate] },
            ]
          : []
      }
      state={rows.length === 0 ? "empty" : "default"}
    />
  )
}

function approvalSteps(model: ReturnType<typeof useConsole>["model"]): readonly ApprovalStep[] {
  const decision = model.snapshot.decision?.state
  return [
    {
      id: "comparison",
      label: "Comparison evidence bound",
      state: model.snapshot.comparison ? "complete" : "pending",
    },
    {
      id: "policy",
      label: "Local policy evaluated",
      state: model.snapshot.approval ? "complete" : "pending",
    },
    {
      id: "decision",
      label: "Evidence-only decision",
      state:
        decision === "rejected" ? "rejected" : decision === "approved" ? "complete" : "pending",
    },
  ]
}

export function ApprovalPanel() {
  const { model, actions } = useConsole()
  if (model.snapshot.comparison === undefined) return null
  const decision = model.snapshot.decision?.state
  const state =
    model.workflow.phase === "approval-blocked"
      ? "disabled"
      : decision === "approved"
        ? "approved"
        : decision === "rejected"
          ? "rejected"
          : "default"
  return (
    <ApprovalEvidence
      state={state}
      decision={decision ?? "pending"}
      steps={approvalSteps(model)}
      {...(model.workflow.phase === "approval-blocked"
        ? { reason: "Policy reasons are unavailable in the current HTTP error contract." }
        : {})}
      {...(model.snapshot.decision
        ? { proofHash: model.snapshot.decision.approval_proof.certificate_hash }
        : {})}
      {...(model.workflow.phase === "approval-pending"
        ? {
            ...(model.busy !== null
              ? { allActionsDisabledReason: `${model.busy} is already in progress.` }
              : {}),
            onApprove: () => void actions.decide("approve"),
            onReject: () => void actions.decide("reject"),
          }
        : {})}
    />
  )
}
