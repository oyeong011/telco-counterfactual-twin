import { describe, expect, it } from "vitest"
import dataCss from "../styles/data.css?raw"
import evidenceCss from "../styles/evidence.css?raw"
import showcaseCss from "../styles/showcase.css?raw"

describe("showcase layout contract", () => {
  it("allows nested grid content to shrink inside the route scroll owner", () => {
    // Given
    const nestedGridRule = /\.showcasePage,\s*\.showcaseStack\s*\{[^}]+\}/

    // When
    const matchingRule = showcaseCss.match(nestedGridRule)?.[0] ?? ""

    // Then
    expect(matchingRule).toContain("min-inline-size: 0")
    expect(matchingRule).toContain("max-inline-size: 100%")
  })

  it("allows direct showcase grid items to shrink below their min-content width", () => {
    // Given
    const gridItemRule = /\.showcasePage\s*>\s*\*,\s*\.showcaseStack\s*>\s*\*\s*\{[^}]+\}/

    // When
    const matchingRule = showcaseCss.match(gridItemRule)?.[0] ?? ""

    // Then
    expect(matchingRule).toContain("min-inline-size: 0")
    expect(matchingRule).toContain("max-inline-size: 100%")
  })

  it("contains topology and timeline content at tablet canvas widths", () => {
    // Given
    const topologyMinimum = "min-inline-size: min(30rem, 100%)"
    const timelineContainerFallback =
      /@container[^}]+\.eventTimeline li\s*\{[^}]+grid-template-columns/

    // When
    const topologyIsShrinkSafe = dataCss.includes(topologyMinimum)
    const timelineIsContainerDriven = timelineContainerFallback.test(evidenceCss)

    // Then
    expect(topologyIsShrinkSafe).toBe(true)
    expect(timelineIsContainerDriven).toBe(true)
  })

  it("keeps the showcase introduction in one readable text column", () => {
    // Given
    const introRule = showcaseCss.match(/\.showcaseIntro\s*\{[^}]+\}/)?.[0] ?? ""

    // When
    const usesSplitColumns = introRule.includes("grid-template-columns")

    // Then
    expect(usesSplitColumns).toBe(false)
  })
})
