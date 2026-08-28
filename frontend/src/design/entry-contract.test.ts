import { render, screen } from "@testing-library/react"
import { createElement } from "react"
import { describe, expect, it } from "vitest"
import { ConsoleApplication } from "../ConsoleApplication"
import { shouldRenderShowcase } from "../showcase/showcaseGate"

describe("document entry contract", () => {
  it("renders the product workbench as a real main landmark without showcase content", async () => {
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
    render(createElement(ConsoleApplication))

    // Then
    expect(await screen.findByRole("main")).toHaveTextContent("Start an isolated evidence session")
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
