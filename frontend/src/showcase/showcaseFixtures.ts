import { Activity, FileCheck2, FlaskConical, Gauge, Network, ShieldCheck } from "lucide-react"
import type { ApprovalStep } from "../design/primitives/ApprovalEvidence"
import type { AppNavigationItem } from "../design/primitives/AppShell"
import type { ContextRailItem } from "../design/primitives/ContextRail"
import type { TimelineEvent } from "../design/primitives/EventTimeline"
import type { EvidenceField } from "../design/primitives/EvidenceRail"
import type { MetricDeltaRow, MetricSeries } from "../design/primitives/MetricDelta"
import type { TopologyEdge, TopologyNode } from "../design/primitives/TopologyCanvas"
import type { PatchLine } from "../design/primitives/TypedPatchDiff"

export const SHOWCASE_NAVIGATION = [
  { label: "Showcase", href: "#__showcase", icon: FlaskConical, active: true },
  { label: "Topology", href: "#topology", icon: Network, active: false },
  { label: "Metrics", href: "#metrics", icon: Gauge, active: false },
  { label: "Activity", href: "#timeline", icon: Activity, active: false },
  { label: "Evidence", href: "#evidence", icon: FileCheck2, active: false },
  { label: "Approval", href: "#approval", icon: ShieldCheck, active: false, disabled: true },
] satisfies readonly AppNavigationItem[]

export const CONTEXT_ITEMS = [
  { id: "run-024", label: "Run 024: radio congestion", metadata: "42m", tone: "stale" },
  { id: "run-023", label: "Run 023: interference", metadata: "approved", tone: "approved" },
  { id: "run-022", label: "Run 022: handover failure", metadata: "rejected", tone: "rejected" },
  {
    id: "run-021",
    label: "Run 021: unavailable fixture",
    metadata: "disabled",
    disabled: true,
    disabledReason: "No topology snapshot is available",
  },
] satisfies readonly ContextRailItem[]

export const TOPOLOGY_NODES = [
  { id: "core", label: "Core DC", x: 50, y: 16, status: "approved" },
  { id: "agg-1", label: "AGG 1", x: 28, y: 44, status: "default" },
  { id: "agg-2", label: "AGG 2", x: 72, y: 44, status: "stale" },
  { id: "site-a", label: "Site A", x: 18, y: 78, status: "default" },
  { id: "site-c", label: "Site C", x: 82, y: 78, status: "rejected" },
] satisfies readonly TopologyNode[]

export const TOPOLOGY_EDGES = [
  {
    id: "core-agg-1",
    sourceId: "core",
    targetId: "agg-1",
    linkType: "core",
    status: "approved",
    impact: "none",
    evidenceId: "fixture-evidence-7f3a",
  },
  {
    id: "core-agg-2",
    sourceId: "core",
    targetId: "agg-2",
    linkType: "core",
    status: "stale",
    impact: "review",
    evidenceId: "fixture-evidence-7f3b",
  },
  {
    id: "agg-1-site-a",
    sourceId: "agg-1",
    targetId: "site-a",
    linkType: "backhaul",
    status: "default",
    impact: "low",
    evidenceId: "fixture-evidence-7f3c",
  },
  {
    id: "agg-2-site-c",
    sourceId: "agg-2",
    targetId: "site-c",
    linkType: "backhaul",
    status: "rejected",
    impact: "high",
    evidenceId: "fixture-evidence-7f3d",
  },
] satisfies readonly TopologyEdge[]

export const METRIC_SERIES = [
  { label: "Baseline", style: "dashed", values: [62, 70, 64, 72, 66, 74, 69, 78] },
  { label: "Candidate", style: "solid", values: [66, 75, 73, 81, 79, 86, 83, 91] },
] satisfies readonly MetricSeries[]

export const METRIC_ROWS = [
  {
    id: "throughput",
    metric: "P95 DL throughput",
    baseline: "142.3 Mbps",
    candidate: "167.8 Mbps",
    delta: "+17.9%",
    direction: "improved",
  },
  {
    id: "latency",
    metric: "P95 latency",
    baseline: "18.6 ms",
    candidate: "21.3 ms",
    delta: "+2.7 ms",
    direction: "degraded",
  },
] satisfies readonly MetricDeltaRow[]

export const TIMELINE_EVENTS = [
  {
    id: "event-1",
    timestamp: "+00:00:01.234",
    type: "Synthetic scenario started",
    impacted: "GLOBAL",
    severity: "info",
    evidenceId: "fixture-evidence-7f3a",
  },
  {
    id: "event-2",
    timestamp: "+00:00:35.221",
    type: "Backhaul utilization high",
    impacted: "SITE_C",
    severity: "warning",
    evidenceId: "fixture-evidence-7f3d",
  },
  {
    id: "event-3",
    timestamp: "+00:00:47.668",
    type: "Policy threshold exceeded",
    impacted: "CORE_DC",
    severity: "critical",
    evidenceId: "fixture-evidence-7f3e",
  },
] satisfies readonly TimelineEvent[]

export const PATCH_LINES = [
  { id: "line-129-context", number: 129, kind: "context", content: "prb_allocation:" },
  {
    id: "line-130-removal",
    number: 130,
    kind: "removal",
    content: "max_prb_utilization: 85",
  },
  {
    id: "line-130-addition",
    number: 130,
    kind: "addition",
    content: "max_prb_utilization: 75",
  },
  { id: "line-131-context", number: 131, kind: "context", content: "min_rb_reserve: 12" },
] satisfies readonly PatchLine[]

export const EVIDENCE_FIELDS = [
  { id: "replay", label: "Replay hash", value: "sha256:fixture-evidence-7f3a" },
  { id: "scenario", label: "Scenario", value: "CF-DEMO-RUN-024" },
  { id: "generated-at", label: "Generated at", value: "2026-08-29T00:00:00Z" },
  { id: "boundary", label: "Boundary", value: "Evidence only. No network execution." },
] satisfies readonly EvidenceField[]

export const APPROVAL_STEPS = [
  { id: "engineer", label: "Engineer review", state: "complete" },
  { id: "policy", label: "Policy constraint review", state: "rejected" },
] satisfies readonly ApprovalStep[]
