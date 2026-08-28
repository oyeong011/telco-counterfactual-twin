import { render, screen } from "@testing-library/react"
import { createElement } from "react"
import { describe, expect, it } from "vitest"
import { PrimitiveShowcase } from "../showcase/PrimitiveShowcase"
import { ThemeProvider } from "./theme/ThemeProvider"

describe("showcase layout contract", () => {
  it("renders nested showcase regions as shrink-safe DOM layout owners", () => {
    // Given
    render(createElement(ThemeProvider, null, createElement(PrimitiveShowcase)))

    // When
    const main = screen.getByRole("main")
    const showcase = main.querySelector<HTMLElement>(".showcasePage")
    const stateGrid = main.querySelector<HTMLElement>(".showcaseStateGrid")
    const error = main.querySelector<HTMLElement>("[data-primitive=ErrorState] .errorState")

    // Then
    expect(showcase).toHaveAttribute("data-layout", "route-stack")
    expect(stateGrid).toHaveAttribute("data-layout", "state-grid")
    expect(error).toHaveAttribute("data-layout", "component-aware")
  })

  it("keeps topology and timeline fallback regions available in the live DOM", () => {
    // Given
    render(createElement(ThemeProvider, null, createElement(PrimitiveShowcase)))

    // When / Then
    const topology = screen.getByRole("region", { name: "TopologyCanvas state gallery" })
    const timeline = screen.getByRole("region", { name: "EventTimeline state gallery" })
    expect(topology.querySelectorAll("table").length).toBeGreaterThan(0)
    expect(timeline.querySelectorAll('ol[aria-label="Simulation trace"]').length).toBeGreaterThan(0)
  })

  it("marks preview route bodies as full shell-body grid owners", () => {
    // Given
    render(createElement(ThemeProvider, null, createElement(PrimitiveShowcase)))

    // When
    const shellError = screen
      .getByRole("region", { name: "AppShell state gallery" })
      .querySelector<HTMLElement>('[data-state="error"]')
    const previewRoute = shellError?.querySelector<HTMLElement>(".showcaseShellRoute")

    // Then
    expect(previewRoute).toHaveAttribute("data-layout", "preview-route")
  })
})
