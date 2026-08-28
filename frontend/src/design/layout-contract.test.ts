import { render, screen } from "@testing-library/react"
import { createElement } from "react"
import { describe, expect, it } from "vitest"
import { PrimitiveShowcase } from "../showcase/PrimitiveShowcase"
import { ThemeProvider } from "./theme/ThemeProvider"

describe("showcase layout contract", () => {
  it("keeps the route and state galleries exposed through semantic regions", () => {
    // Given
    render(createElement(ThemeProvider, null, createElement(PrimitiveShowcase)))

    // When
    const main = screen.getByRole("main")
    const errorGallery = screen.getByRole("region", { name: "ErrorState state gallery" })

    // Then
    expect(main).toContainElement(errorGallery)
    expect(screen.getByRole("heading", { name: "Evidence-first console primitives" })).toBeVisible()
    expect(screen.getAllByRole("article").length).toBeGreaterThan(0)
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

  it("renders a recoverable error inside the AppShell preview", () => {
    // Given
    render(createElement(ThemeProvider, null, createElement(PrimitiveShowcase)))

    // When
    const shellError = screen
      .getByRole("region", { name: "AppShell state gallery" })
      .querySelector<HTMLElement>('[data-state="error"]')
    if (!(shellError instanceof HTMLElement)) {
      throw new TypeError("AppShell error preview is missing")
    }

    // Then
    expect(
      screen.getByRole("navigation", { name: "AppShell error preview navigation" }),
    ).toBeVisible()
    expect(screen.getByRole("alert", { name: "Shell route unavailable" })).toBeVisible()
  })
})
