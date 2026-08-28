import { render, screen, within } from "@testing-library/react"
import { beforeEach, describe, expect, it } from "vitest"
import { ThemeProvider } from "../design/theme/ThemeProvider"
import { PrimitiveShowcase } from "./PrimitiveShowcase"

const ALL_STATES = [
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

const EXPECTED_STATES = {
  AppShell: ALL_STATES,
  CommandBar: ALL_STATES,
  ContextRail: ALL_STATES,
  StatusChip: ALL_STATES.filter((state) => state !== "empty"),
  DataTable: ALL_STATES,
  TopologyCanvas: ALL_STATES,
  EventTimeline: ALL_STATES,
  MetricDelta: ALL_STATES,
  TypedPatchDiff: ALL_STATES,
  EvidenceRail: ALL_STATES,
  ApprovalEvidence: ALL_STATES,
  ErrorState: ALL_STATES.filter((state) => state !== "empty" && state !== "approved"),
  Skeleton: ["loading"],
} as const

const KOREAN_COPY = "승인은 증거만 기록하며 네트워크를 실행하지 않습니다."
const KOREAN_HASH = "sha256:한글-증거-해시-0123456789abcdef0123456789abcdef"

function stubMatchMedia() {
  beforeEach(() => {
    Object.defineProperty(window, "matchMedia", {
      configurable: true,
      value: (query: string) => ({
        matches: query === "(prefers-color-scheme: dark)",
        media: query,
        onchange: null,
        addEventListener() {},
        removeEventListener() {},
        addListener() {},
        removeListener() {},
        dispatchEvent() {
          return false
        },
      }),
    })
  })
}

describe("primitive showcase coverage", () => {
  stubMatchMedia()

  it("renders every DESIGN primitive with its applicable state examples", () => {
    // Given
    render(
      <ThemeProvider>
        <PrimitiveShowcase />
      </ThemeProvider>,
    )

    // When
    for (const [primitive, states] of Object.entries(EXPECTED_STATES)) {
      const section = screen.getByRole("region", { name: `${primitive} state gallery` })
      const renderedStates = Array.from(
        section.querySelectorAll<HTMLElement>(".showcaseStateCard"),
        (item) => item.getAttribute("data-state") ?? undefined,
      )

      // Then
      expect(section).toHaveAttribute("data-primitive", primitive)
      expect(renderedStates).toEqual(states)
      expect(new Set(renderedStates).size).toBe(states.length)
    }
  })

  it("provides an anchor for every primitive state gallery", () => {
    // Given
    render(
      <ThemeProvider>
        <PrimitiveShowcase />
      </ThemeProvider>,
    )

    // When / Then
    for (const primitive of Object.keys(EXPECTED_STATES)) {
      const section = screen.getByRole("region", { name: `${primitive} state gallery` })
      const heading = within(section).getByRole("heading", { name: primitive, level: 2 })
      expect(heading).toBeVisible()
      expect(screen.getByRole("link", { name: primitive })).toHaveAttribute(
        "href",
        `#primitive-${primitive.toLowerCase()}`,
      )
    }
  })

  it("renders the Korean evidence copy and long hash as real text", () => {
    // Given
    render(
      <ThemeProvider>
        <PrimitiveShowcase />
      </ThemeProvider>,
    )

    // When / Then
    expect(screen.getByText(KOREAN_COPY)).toBeVisible()
    expect(screen.getByText(KOREAN_HASH)).toBeVisible()
  })
})
