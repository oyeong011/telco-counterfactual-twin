export const SURFACE_STATES = [
  "default",
  "disabled",
  "loading",
  "empty",
  "error",
  "stale",
  "rejected",
  "approved",
  "demo",
] as const

export type SurfaceState = (typeof SURFACE_STATES)[number]

export const SKELETON_VARIANTS = [
  "table",
  "timeline",
  "chart",
  "topology",
  "code",
  "evidence",
] as const

export type SkeletonVariant = (typeof SKELETON_VARIANTS)[number]

export const SURFACE_TONES = {
  default: "neutral",
  disabled: "neutral",
  loading: "loading",
  empty: "neutral",
  error: "danger",
  stale: "stale",
  rejected: "rejected",
  approved: "approved",
  demo: "demo",
} as const satisfies Record<SurfaceState, string>
