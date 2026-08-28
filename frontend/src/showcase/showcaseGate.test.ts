import { describe, expect, it } from "vitest"
import { shouldRenderShowcase } from "./showcaseGate"

describe("primitive showcase gate", () => {
  it("opens only on the exact development-only path", () => {
    // Given
    const developmentRequest = { isDevelopment: true, pathname: "/__showcase" }

    // When
    const allowed = shouldRenderShowcase(developmentRequest)

    // Then
    expect(allowed).toBe(true)
  })

  it("stays closed for production and near-match paths", () => {
    // Given
    const requests = [
      { isDevelopment: false, pathname: "/__showcase" },
      { isDevelopment: true, pathname: "/__showcase/fixtures" },
      { isDevelopment: true, pathname: "/" },
    ] as const

    // When
    const decisions = requests.map(shouldRenderShowcase)

    // Then
    expect(decisions).toEqual([false, false, false])
  })
})
