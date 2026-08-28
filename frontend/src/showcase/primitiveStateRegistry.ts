import type { SurfaceState } from "../design/primitives/primitiveTypes"

export const SHOWCASE_INTERACTION_STATES = [
  "default",
  "hover",
  "active",
  "focus",
  "disabled",
  "loading",
  "empty",
  "error",
  "stale",
  "rejected",
  "approved",
  "demo",
] as const

export type ShowcaseState = (typeof SHOWCASE_INTERACTION_STATES)[number]

export const PRIMITIVE_NAMES = [
  "AppShell",
  "CommandBar",
  "ContextRail",
  "StatusChip",
  "DataTable",
  "TopologyCanvas",
  "EventTimeline",
  "MetricDelta",
  "TypedPatchDiff",
  "EvidenceRail",
  "ApprovalEvidence",
  "ErrorState",
  "Skeleton",
] as const

export type ShowcasePrimitive = (typeof PRIMITIVE_NAMES)[number]

const STATUS_CHIP_STATES = SHOWCASE_INTERACTION_STATES.filter((state) => state !== "empty")
const ERROR_STATE_STATES = SHOWCASE_INTERACTION_STATES.filter(
  (state) => state !== "empty" && state !== "approved",
)

export const PRIMITIVE_APPLICABLE_STATES = {
  AppShell: SHOWCASE_INTERACTION_STATES,
  CommandBar: SHOWCASE_INTERACTION_STATES,
  ContextRail: SHOWCASE_INTERACTION_STATES,
  StatusChip: STATUS_CHIP_STATES,
  DataTable: SHOWCASE_INTERACTION_STATES,
  TopologyCanvas: SHOWCASE_INTERACTION_STATES,
  EventTimeline: SHOWCASE_INTERACTION_STATES,
  MetricDelta: SHOWCASE_INTERACTION_STATES,
  TypedPatchDiff: SHOWCASE_INTERACTION_STATES,
  EvidenceRail: SHOWCASE_INTERACTION_STATES,
  ApprovalEvidence: SHOWCASE_INTERACTION_STATES,
  ErrorState: ERROR_STATE_STATES,
  Skeleton: ["loading"],
} as const satisfies Readonly<Record<ShowcasePrimitive, readonly ShowcaseState[]>>

export function primitiveAnchor(primitive: ShowcasePrimitive): string {
  return `primitive-${primitive.toLowerCase()}`
}

function assertNever(value: never): never {
  throw new TypeError(`Unsupported showcase state: ${String(value)}`)
}

export function surfaceStateFor(state: ShowcaseState): SurfaceState {
  switch (state) {
    case "hover":
    case "active":
    case "focus":
      return "default"
    case "default":
    case "disabled":
    case "loading":
    case "empty":
    case "error":
    case "stale":
    case "rejected":
    case "approved":
    case "demo":
      return state
    default:
      return assertNever(state)
  }
}
