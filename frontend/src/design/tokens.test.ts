import { afterEach, describe, expect, it } from "vitest"
import "../styles/tokens.css"

const EXPECTED_THEME_TOKENS = {
  light: {
    "--surface-root": "#f6f1f4",
    "--surface-panel": "#fff9fc",
    "--text-primary": "#211824",
    "--text-secondary": "#5d5062",
    "--border-subtle": "#ded1dc",
    "--accent-primary": "#65408a",
    "--accent-proof": "#527a23",
    "--accent-warning": "#9a5b17",
    "--accent-danger": "#ad3f36",
    "--chart-baseline": "#6a5c71",
    "--chart-candidate": "#65408a",
  },
  dark: {
    "--surface-root": "#171019",
    "--surface-panel": "#201724",
    "--text-primary": "#f7eff8",
    "--text-secondary": "#c3b4c8",
    "--border-subtle": "#372b3d",
    "--accent-primary": "#b890e6",
    "--accent-proof": "#a4d65e",
    "--accent-warning": "#e2a04d",
    "--accent-danger": "#f07a68",
    "--chart-baseline": "#b8a7c1",
    "--chart-candidate": "#c09af0",
  },
} as const

const EXPECTED_FOUNDATION_TOKENS = {
  "--space-1": "0.25rem",
  "--space-10": "2.5rem",
  "--font-body": '"Rubik Variable", "Rubik", sans-serif',
  "--font-mono": '"IBM Plex Mono", monospace',
  "--text-body": "0.875rem",
  "--target-min": "2.75rem",
  "--radius-panel": "0.375rem",
  "--motion-standard": "160ms",
} as const

function computedToken(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
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
  afterEach(() => document.documentElement.removeAttribute("data-theme"))

  it("renders the independently specified DESIGN palette in both themes", () => {
    for (const [theme, tokens] of Object.entries(EXPECTED_THEME_TOKENS)) {
      // Given
      document.documentElement.setAttribute("data-theme", theme)

      // When / Then
      for (const [name, expected] of Object.entries(tokens)) {
        expect(computedToken(name)).toBe(expected)
      }
    }
  })

  it("renders the independently specified spacing, type, target, radius, and motion scales", () => {
    // Given
    document.documentElement.setAttribute("data-theme", "light")

    // When / Then
    for (const [name, expected] of Object.entries(EXPECTED_FOUNDATION_TOKENS)) {
      expect(computedToken(name)).toBe(expected)
    }
  })

  it("keeps rendered light proof and warning pairs above WCAG AA body contrast", () => {
    // Given
    document.documentElement.setAttribute("data-theme", "light")

    // When
    const warningRatio = contrastRatio(
      computedToken("--accent-warning"),
      computedToken("--state-warning"),
    )
    const proofRatio = contrastRatio(
      computedToken("--accent-proof"),
      computedToken("--state-proof"),
    )

    // Then
    expect(warningRatio).toBeGreaterThanOrEqual(4.5)
    expect(proofRatio).toBeGreaterThanOrEqual(4.5)
  })
})
