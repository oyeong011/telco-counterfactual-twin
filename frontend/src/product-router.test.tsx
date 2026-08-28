import { createMemoryHistory } from "@tanstack/react-router"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { ConsoleApplication } from "./ConsoleApplication"
import { createConsoleApiFixture } from "./test/consoleApi"

describe("product router", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(new Response(null, { status: 404 }))),
    )
  })

  it("navigates the five production routes without a fixture route", async () => {
    const history = createMemoryHistory({ initialEntries: ["/"] })
    render(<ConsoleApplication client={createConsoleApiFixture().client} history={history} />)
    const user = userEvent.setup()

    await user.click(await screen.findByRole("link", { name: "Benchmarks" }))
    expect(await screen.findByRole("heading", { name: "Benchmark lab" })).toBeVisible()
    await user.click(screen.getByRole("link", { name: "About" }))
    expect(
      await screen.findByRole("heading", { level: 1, name: "System boundaries" }),
    ).toBeVisible()
    expect(document.title).toBe("System boundaries · Telco Counterfactual Twin Console")
    expect(screen.getByRole("main")).toHaveFocus()
    expect(document.querySelector('a[href="/showcase"]')).toBeNull()
  })

  it("shows an actionable non-leaking state for a run deep link without an in-memory token", async () => {
    sessionStorage.setItem("telco-twin:run-drafts:session-old", "sensitive-prior-patch")
    const history = createMemoryHistory({ initialEntries: ["/runs/run-001"] })
    render(<ConsoleApplication client={createConsoleApiFixture().client} history={history} />)

    expect(await screen.findByText("Session context missing")).toBeVisible()
    expect(screen.getByText(/in-memory session token/)).toBeVisible()
    expect(screen.getByRole("button", { name: "Open Workbench" })).toBeVisible()
    expect(document.body).not.toHaveTextContent("sensitive-prior-patch")
    expect(document.body).not.toHaveTextContent("demo-token-secret")
  })
})
