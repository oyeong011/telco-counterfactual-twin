import { createMemoryHistory } from "@tanstack/react-router"
import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { ConsoleApplication } from "./ConsoleApplication"
import { createConsoleApiFixture } from "./test/consoleApi"

async function renderAboutAfterDecision(decision: "approved" | "rejected") {
  const history = createMemoryHistory({ initialEntries: ["/"] })
  render(<ConsoleApplication client={createConsoleApiFixture().client} history={history} />)
  const user = userEvent.setup()
  for (const label of [
    "Start synthetic session",
    "Create scenario",
    "Diagnose scenario",
    "Validate and propose patch",
    "Simulate candidate",
    "Compare evidence",
    "Request approval evidence",
    decision === "approved" ? "Record approval evidence" : "Record rejection evidence",
  ]) {
    await user.click(await screen.findByRole("button", { name: label }))
  }
  await user.click(screen.getByRole("link", { name: "About" }))
  return screen.findByRole("region", { name: "Current evidence-only decision" })
}

beforeEach(() => {
  sessionStorage.clear()
  vi.stubGlobal(
    "fetch",
    vi.fn(() => Promise.reject(new TypeError("build info unavailable"))),
  )
})

afterEach(() => vi.unstubAllGlobals())

describe("About decision outcome", () => {
  it("shows the backend-approved outcome as evidence only", async () => {
    // Given / When
    const outcome = await renderAboutAfterDecision("approved")

    // Then
    expect(outcome).toHaveAttribute("data-decision", "approved")
    expect(within(outcome).getByText("Approved").closest(".statusChip")).toHaveAttribute(
      "data-tone",
      "approved",
    )
    expect(outcome).toHaveTextContent(/did not execute a network change/i)
    expect(outcome).not.toHaveTextContent(/verified/i)
  })

  it("shows the backend-rejected outcome as a distinct evidence-only state", async () => {
    // Given / When
    const outcome = await renderAboutAfterDecision("rejected")

    // Then
    expect(outcome).toHaveAttribute("data-decision", "rejected")
    expect(within(outcome).getByText("Rejected").closest(".statusChip")).toHaveAttribute(
      "data-tone",
      "rejected",
    )
    expect(outcome).toHaveTextContent(/did not execute a network change/i)
    expect(outcome).not.toHaveTextContent(/verified/i)
  })
})
