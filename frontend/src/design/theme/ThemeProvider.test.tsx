import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { ThemeProvider, useTheme } from "./ThemeProvider"

function ThemeProbe() {
  const theme = useTheme()
  return (
    <div>
      <output aria-label="Resolved theme">{theme.resolvedTheme}</output>
      <button type="button" onClick={() => theme.setPreference("light")}>
        Use light theme
      </button>
    </div>
  )
}

describe("ThemeProvider", () => {
  beforeEach(() => {
    window.localStorage.clear()
    document.documentElement.removeAttribute("data-theme")
  })

  it("resolves the system preference when no stored preference exists", () => {
    // Given
    vi.stubGlobal(
      "matchMedia",
      vi.fn(() => ({
        matches: true,
        media: "(prefers-color-scheme: dark)",
        onchange: null,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        addListener: vi.fn(),
        removeListener: vi.fn(),
        dispatchEvent: vi.fn(),
      })),
    )

    // When
    render(
      <ThemeProvider>
        <ThemeProbe />
      </ThemeProvider>,
    )

    // Then
    expect(screen.getByLabelText("Resolved theme")).toHaveTextContent("dark")
    expect(document.documentElement).toHaveAttribute("data-theme", "dark")
  })

  it("stores an explicit preference selected by the user", async () => {
    // Given
    const user = userEvent.setup()
    vi.stubGlobal(
      "matchMedia",
      vi.fn(() => ({
        matches: true,
        media: "(prefers-color-scheme: dark)",
        onchange: null,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        addListener: vi.fn(),
        removeListener: vi.fn(),
        dispatchEvent: vi.fn(),
      })),
    )
    render(
      <ThemeProvider>
        <ThemeProbe />
      </ThemeProvider>,
    )

    // When
    await user.click(screen.getByRole("button", { name: "Use light theme" }))

    // Then
    expect(window.localStorage.getItem("twin-theme")).toBe("light")
    expect(document.documentElement).toHaveAttribute("data-theme", "light")
  })
})
