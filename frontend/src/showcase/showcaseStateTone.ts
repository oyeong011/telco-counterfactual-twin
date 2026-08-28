import type { StatusTone } from "../design/primitives/StatusChip"
import type { ShowcaseState } from "./primitiveStateRegistry"

export function stateTone(state: ShowcaseState): StatusTone {
  switch (state) {
    case "default":
    case "disabled":
    case "empty":
      return "neutral"
    case "hover":
    case "active":
    case "focus":
      return "info"
    case "loading":
      return "loading"
    case "error":
      return "danger"
    case "stale":
      return "stale"
    case "rejected":
      return "rejected"
    case "approved":
      return "approved"
    case "demo":
      return "demo"
    default: {
      const exhaustiveState: never = state
      throw new TypeError(`Unsupported showcase state: ${String(exhaustiveState)}`)
    }
  }
}
