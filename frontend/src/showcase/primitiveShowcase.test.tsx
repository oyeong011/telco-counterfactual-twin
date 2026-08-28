import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it } from "vitest"
import { ThemeProvider } from "../design/theme/ThemeProvider"
import { PrimitiveShowcase } from "./PrimitiveShowcase"

const KOREAN_COPY = "승인은 증거만 기록하며 네트워크를 실행하지 않습니다."
const KOREAN_HASH = "sha256:한글-증거-해시-0123456789abcdef0123456789abcdef"
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
const EXPECTED_STATE_COVERAGE = {
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
    for (const [primitive, states] of Object.entries(EXPECTED_STATE_COVERAGE)) {
      const section = screen.getByRole("region", { name: `${primitive} state gallery` })
      const renderedStates = Array.from(
        section.querySelectorAll<HTMLElement>(".showcaseStateCard"),
        (item) => item.getAttribute("data-state") ?? undefined,
      )

      // Then
      expect(section).toHaveAttribute("data-primitive", primitive)
      expect(renderedStates).toEqual(states)
    }
  })

  it("renders AppShell states as real shell content and interaction states", () => {
    // Given
    render(
      <ThemeProvider>
        <PrimitiveShowcase />
      </ThemeProvider>,
    )
    const section = screen.getByRole("region", { name: "AppShell state gallery" })

    // When
    const card = (state: string) => section.querySelector(`[data-state="${state}"]`)

    // Then
    expect(card("loading")?.querySelector('[data-variant="table"]')).not.toBeNull()
    expect(card("empty")?.querySelector(".emptyMessage")).not.toBeNull()
    expect(card("error")?.querySelector(".errorState")).not.toBeNull()
    expect(card("stale")?.querySelector('[data-tone="stale"]')).not.toBeNull()
    expect(card("rejected")?.querySelector('[data-tone="rejected"]')).not.toBeNull()
    expect(card("approved")?.querySelector('[data-tone="approved"]')).not.toBeNull()
    expect(card("demo")?.querySelector('[data-tone="demo"]')).not.toBeNull()
    expect(card("active")?.querySelector('[aria-current="page"]')).not.toBeNull()
    expect(card("disabled")?.querySelector('a[aria-disabled="true"]')).not.toBeNull()
    const focusLink = card("focus")?.querySelector<HTMLAnchorElement>("a")
    focusLink?.focus()
    expect(focusLink).toHaveFocus()
  })

  it("keeps each command state attached to an actionable control", async () => {
    // Given
    const user = userEvent.setup()
    render(
      <ThemeProvider>
        <PrimitiveShowcase />
      </ThemeProvider>,
    )
    const section = screen.getByRole("region", { name: "CommandBar state gallery" })
    const card = (state: string) => section.querySelector(`[data-state="${state}"]`)
    const activeReview = card("active")?.querySelector<HTMLButtonElement>("button")

    // When
    if (activeReview === null || activeReview === undefined) {
      throw new Error("CommandBar active state is missing its action")
    }
    await user.click(activeReview)

    // Then
    expect(activeReview).toHaveAttribute("aria-pressed", "true")
    const focusAction = card("focus")?.querySelector<HTMLButtonElement>("button")
    focusAction?.focus()
    expect(focusAction).toHaveFocus()
    expect(card("disabled")?.querySelector("button")).toBeDisabled()
    expect(card("loading")?.querySelector("button")).toBeDisabled()
    expect(card("error")).toHaveTextContent(/recovery remains evidence-only/i)
  })

  it("provides an anchor for every primitive state gallery", () => {
    // Given
    render(
      <ThemeProvider>
        <PrimitiveShowcase />
      </ThemeProvider>,
    )

    // When / Then
    for (const primitive of Object.keys(EXPECTED_STATE_COVERAGE)) {
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
    expect(screen.getAllByText(KOREAN_HASH).length).toBeGreaterThan(0)
  })
})
