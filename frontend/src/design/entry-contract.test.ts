import { render, screen } from "@testing-library/react"
import { createElement } from "react"
import { describe, expect, it } from "vitest"
import { ThemeProvider } from "../design/theme/ThemeProvider"
import { FoundationApp } from "../FoundationApp"
import { shouldRenderShowcase } from "../showcase/showcaseGate"

describe("document entry contract", () => {
  it("renders the foundation route as a real main landmark without showcase content", () => {
    // Given
    Object.defineProperty(window, "matchMedia", {
      configurable: true,
      value: () => ({
        matches: false,
        media: "(prefers-color-scheme: dark)",
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

    // When
    render(createElement(ThemeProvider, null, createElement(FoundationApp)))

    // Then
    expect(screen.getByRole("main")).toHaveTextContent("Console foundation")
    expect(screen.queryByRole("region", { name: /state gallery/i })).not.toBeInTheDocument()
  })

  it("uses the exact showcase gate decision for entry routing", () => {
    // Given
    const requests = [
      { isDevelopment: true, pathname: "/__showcase" },
      { isDevelopment: false, pathname: "/__showcase" },
      { isDevelopment: true, pathname: "/__showcase/fixtures" },
    ] as const

    // When
    const decisions = requests.map(shouldRenderShowcase)

    // Then
    expect(decisions).toEqual([true, false, false])
  })
})
