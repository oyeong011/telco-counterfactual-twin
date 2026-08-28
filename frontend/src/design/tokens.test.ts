import { describe, expect, it } from "vitest"
import tokenCss from "../styles/tokens.css?raw"

function cssToken(block: string, name: string): string {
  const match = block.match(new RegExp(`${name}:\\s*(#[0-9a-f]{6})`, "i"))
  const value = match?.[1]
  if (!value) throw new TypeError(`Missing color token ${name}`)
  return value
}

function linearChannel(color: string, start: number): number {
  const channel = Number.parseInt(color.slice(start, start + 2), 16) / 255
  return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4
}

function luminance(color: string): number {
  return (
    0.2126 * linearChannel(color, 1) +
    0.7152 * linearChannel(color, 3) +
    0.0722 * linearChannel(color, 5)
  )
}

function contrastRatio(foreground: string, background: string): number {
  const lighter = Math.max(luminance(foreground), luminance(background))
  const darker = Math.min(luminance(foreground), luminance(background))
  return (lighter + 0.05) / (darker + 0.05)
}

describe("design tokens", () => {
  it("defines the semantic color contract for both explicit themes", () => {
    // Given
    const requiredTokens = [
      "--surface-root",
      "--surface-panel",
      "--text-primary",
      "--text-secondary",
      "--border-subtle",
      "--accent-primary",
      "--accent-proof",
      "--accent-warning",
      "--accent-danger",
      "--chart-baseline",
      "--chart-candidate",
    ]

    // When
    const themeBlocks = tokenCss.match(/\[data-theme="(?:light|dark)"\][^{]*\{[^}]+\}/g) ?? []

    // Then
    expect(themeBlocks).toHaveLength(2)
    for (const token of requiredTokens) {
      expect(themeBlocks.every((block) => block.includes(token))).toBe(true)
    }
  })

  it("defines the spacing, type, target, radius, and motion scales", () => {
    // Given
    const requiredTokens = [
      "--space-1",
      "--space-10",
      "--font-body",
      "--font-mono",
      "--text-body",
      "--target-min",
      "--radius-panel",
      "--motion-standard",
    ]

    // When
    const availableTokens = requiredTokens.filter((token) => tokenCss.includes(token))

    // Then
    expect(availableTokens).toEqual(requiredTokens)
  })

  it("keeps light proof and warning state pairs above WCAG AA body contrast", () => {
    // Given
    const lightBlock = tokenCss.match(/\[data-theme="light"\][^{]*\{[^}]+\}/)?.[0]
    if (!lightBlock) throw new TypeError("Light theme token block is missing")

    // When
    const warningRatio = contrastRatio(
      cssToken(lightBlock, "--accent-warning"),
      cssToken(lightBlock, "--state-warning"),
    )
    const proofRatio = contrastRatio(
      cssToken(lightBlock, "--accent-proof"),
      cssToken(lightBlock, "--state-proof"),
    )

    // Then
    expect(warningRatio).toBeGreaterThanOrEqual(4.5)
    expect(proofRatio).toBeGreaterThanOrEqual(4.5)
  })
})
