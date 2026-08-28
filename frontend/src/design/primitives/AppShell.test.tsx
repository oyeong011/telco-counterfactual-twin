import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { Activity, Network } from "lucide-react"
import { describe, expect, it } from "vitest"
import { AppShell } from "./AppShell"

const navigation = [
  { label: "Workbench", href: "#workbench", icon: Network, active: true },
  { label: "Activity", href: "#activity", icon: Activity, active: false },
] as const

describe("AppShell", () => {
  it("exposes a bounded landmark shell with current navigation", () => {
    // Given
    const mainContent = <h1>Primitive workbench</h1>

    // When
    render(
      <AppShell navigation={navigation} commandBar={<div>Command bar</div>}>
        {mainContent}
      </AppShell>,
    )

    // Then
    expect(screen.getByRole("link", { name: "Skip to main content" })).toHaveAttribute(
      "href",
      "#main-content",
    )
    expect(screen.getByRole("navigation", { name: "Primary" })).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "Workbench" })).toHaveAttribute("aria-current", "page")
    expect(screen.getByRole("main")).toHaveAttribute("id", "main-content")
  })

  it("places the skip link first in keyboard order", async () => {
    // Given
    const user = userEvent.setup()
    render(<AppShell navigation={navigation}>Main content</AppShell>)

    // When
    await user.tab()

    // Then
    expect(screen.getByRole("link", { name: "Skip to main content" })).toHaveFocus()
  })
})
