import { createMemoryHistory } from "@tanstack/react-router"
import { fireEvent, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it } from "vitest"
import { ContractParseError } from "./api/errors"
import { ConsoleApplication } from "./ConsoleApplication"
import type { ApiFailure } from "./contracts/generated"
import { type ConsoleApiFixture, createConsoleApiFixture } from "./test/consoleApi"

function renderConsole(fixture: ConsoleApiFixture, path = "/") {
  const history = createMemoryHistory({ initialEntries: [path] })
  render(<ConsoleApplication client={fixture.client} history={history} />)
}

function sessionValues(): string {
  return Array.from({ length: sessionStorage.length }, (_, index) =>
    sessionStorage.getItem(sessionStorage.key(index) ?? ""),
  ).join("")
}

async function bootstrapAndCreate(fixture: ConsoleApiFixture): Promise<void> {
  renderConsole(fixture)
  const user = userEvent.setup()
  await user.click(await screen.findByRole("button", { name: "Start synthetic session" }))
  await user.click(await screen.findByRole("button", { name: "Create scenario" }))
}

async function advanceToComparison(fixture: ConsoleApiFixture): Promise<void> {
  await bootstrapAndCreate(fixture)
  const user = userEvent.setup()
  await user.click(await screen.findByRole("button", { name: "Diagnose scenario" }))
  await user.click(await screen.findByRole("button", { name: "Validate and propose patch" }))
  await user.click(await screen.findByRole("button", { name: "Simulate candidate" }))
  await user.click(await screen.findByRole("button", { name: "Compare evidence" }))
}

const policyFailure: ApiFailure = {
  ok: false,
  problem: {
    type: "https://telco-twin.invalid/problems/policy_ineligible",
    title: "Policy ineligible",
    status: 422,
    code: "policy_ineligible",
    detail: "The comparison did not satisfy the local policy.",
    request_id: "request-policy-001",
  },
  requestId: "request-policy-001",
}

beforeEach(() => sessionStorage.clear())

describe("governed console lifecycle", () => {
  it("labels metric deltas as neutral changes without inventing an optimization direction", async () => {
    const fixture = createConsoleApiFixture()
    await advanceToComparison(fixture)

    expect(screen.getByRole("cell", { name: "changed" })).toBeVisible()
    expect(screen.queryByRole("cell", { name: "improved" })).not.toBeInTheDocument()
    expect(screen.queryByRole("cell", { name: "degraded" })).not.toBeInTheDocument()
  })

  it("captures an edited scenario seed before React clears the event", async () => {
    const fixture = createConsoleApiFixture()
    renderConsole(fixture)
    const user = userEvent.setup()
    await user.click(await screen.findByRole("button", { name: "Start synthetic session" }))
    const seed = await screen.findByLabelText("Deterministic seed")

    await user.clear(seed)
    await user.type(seed, "42")
    await user.click(screen.getByRole("button", { name: "Create scenario" }))

    expect(fixture.scenarioInputs).toEqual([{ fault_family: "radio-congestion", seed: 42 }])
  })

  it("keeps an empty scenario seed local and shows an actionable field error", async () => {
    const fixture = createConsoleApiFixture()
    renderConsole(fixture)
    const user = userEvent.setup()
    await user.click(await screen.findByRole("button", { name: "Start synthetic session" }))
    await user.clear(await screen.findByLabelText("Deterministic seed"))
    await user.click(screen.getByRole("button", { name: "Create scenario" }))

    expect(await screen.findByText(/Seed must be a whole number/)).toBeVisible()
    expect(fixture.scenarioInputs).toEqual([])
  })

  it("records an approved evidence-only lifecycle without implying execution", async () => {
    const fixture = createConsoleApiFixture()
    await advanceToComparison(fixture)
    const user = userEvent.setup()

    await user.click(await screen.findByRole("button", { name: "Request approval evidence" }))
    await user.click(await screen.findByRole("button", { name: "Record approval evidence" }))
    await user.click(await screen.findByRole("button", { name: "Load evidence package" }))

    expect(await screen.findByText("Evidence package verified")).toBeVisible()
    expect(screen.getAllByText("approved", { selector: "span" }).length).toBeGreaterThan(0)
    expect(screen.queryByRole("button", { name: /execute/i })).not.toBeInTheDocument()
  })

  it("records a rejected evidence-only lifecycle with one idempotency key per mutation", async () => {
    const fixture = createConsoleApiFixture()
    await advanceToComparison(fixture)
    const user = userEvent.setup()

    await user.click(await screen.findByRole("button", { name: "Request approval evidence" }))
    await user.click(await screen.findByRole("button", { name: "Record rejection evidence" }))
    await user.click(await screen.findByRole("button", { name: "Load evidence package" }))

    expect(await screen.findByText("Evidence package verified")).toBeInTheDocument()
    expect(
      screen.getByText("Approval records evidence only. It never executes a patch."),
    ).toBeVisible()
    expect(screen.getByText("Blast radius")).toBeVisible()
    expect(screen.getAllByText("Certificate hash").length).toBeGreaterThan(0)
    expect(screen.getAllByText("rejected", { selector: "span" }).length).toBeGreaterThan(0)
    expect(document.body).not.toHaveTextContent("demo-token-secret")
    expect(sessionValues()).not.toContain("demo-token-secret")
    expect(fixture.idempotencyKeys).toHaveLength(7)
    expect(new Set(fixture.idempotencyKeys).size).toBe(7)
  })

  it("rejects invalid patch JSON locally without sending a mutation", async () => {
    const fixture = createConsoleApiFixture()
    await bootstrapAndCreate(fixture)
    const user = userEvent.setup()
    await user.click(await screen.findByRole("button", { name: "Diagnose scenario" }))
    await user.clear(await screen.findByLabelText("Patch parameters (JSON)"))
    fireEvent.change(screen.getByLabelText("Patch parameters (JSON)"), { target: { value: "{" } })
    await user.click(screen.getByRole("button", { name: "Validate and propose patch" }))

    expect(await screen.findByText("Parameters must be valid JSON.")).toBeVisible()
    expect(fixture.idempotencyKeys).toHaveLength(2)
  })

  it("replaces a stale server failure with the latest local validation error", async () => {
    const patchFailure: ApiFailure = {
      ok: false,
      problem: {
        type: "https://telco-twin.invalid/problems/unsupported-patch-parameters",
        title: "Patch rejected",
        status: 422,
        code: "unsupported-patch-parameters",
        detail: "The typed patch is not valid for this scenario baseline.",
        request_id: "request-patch-r2",
      },
      requestId: "request-patch-r2",
    }
    const fixture = createConsoleApiFixture({ patchFailure })
    await bootstrapAndCreate(fixture)
    const user = userEvent.setup()
    await user.click(await screen.findByRole("button", { name: "Diagnose scenario" }))
    await user.click(await screen.findByRole("button", { name: "Validate and propose patch" }))
    expect(await screen.findByText("unsupported-patch-parameters")).toBeVisible()

    fireEvent.change(screen.getByLabelText("Patch parameters (JSON)"), { target: { value: "{" } })
    await user.click(screen.getByRole("button", { name: "Validate and propose patch" }))

    expect(await screen.findByText("Parameters must be valid JSON.")).toBeVisible()
    expect(screen.queryByText("unsupported-patch-parameters")).not.toBeInTheDocument()
  })

  it("shows the exact policy failure and the backend explainability gap", async () => {
    const fixture = createConsoleApiFixture({ policyFailure })
    await advanceToComparison(fixture)
    const user = userEvent.setup()
    await user.click(await screen.findByRole("button", { name: "Request approval evidence" }))

    expect(await screen.findByText("policy_ineligible")).toBeVisible()
    expect(screen.getByText("Request request-policy-001")).toBeVisible()
    expect(screen.getByText(/does not return policy reasons/)).toBeVisible()
    expect(screen.queryByText(/telemetry was stale/i)).not.toBeInTheDocument()
  })

  it("distinguishes an API outage with its stable code and request id", async () => {
    const outage: ApiFailure = {
      ok: false,
      problem: {
        type: "https://telco-twin.invalid/problems/client_network_error",
        title: "Client network error",
        status: 503,
        code: "client_network_error",
        detail: "The service could not be reached.",
        request_id: "request-outage-001",
      },
      requestId: "request-outage-001",
    }
    renderConsole(createConsoleApiFixture({ bootstrapFailure: outage }))
    const user = userEvent.setup()
    await user.click(await screen.findByRole("button", { name: "Start synthetic session" }))

    expect(await screen.findByText("client_network_error")).toBeVisible()
    expect(screen.getByText("Request request-outage-001")).toBeVisible()
  })

  it("surfaces a thrown boundary parser failure instead of leaving the UI busy", async () => {
    renderConsole(
      createConsoleApiFixture({
        bootstrapException: new ContractParseError("response violated the public contract"),
      }),
    )
    const user = userEvent.setup()
    await user.click(await screen.findByRole("button", { name: "Start synthetic session" }))

    expect(await screen.findByText("client_contract_error")).toBeVisible()
    expect(screen.getByRole("button", { name: "Reset session context" })).toBeVisible()
  })

  it("drops in-memory authority and prior payloads when the backend reports a lost session", async () => {
    const lost: ApiFailure = {
      ok: false,
      problem: {
        type: "https://telco-twin.invalid/problems/demo_session_lost",
        title: "Demo session lost",
        status: 410,
        code: "demo_session_lost",
        detail: "The process-memory session ended after a service restart.",
        request_id: "request-lost-001",
      },
      requestId: "request-lost-001",
    }
    const fixture = createConsoleApiFixture({ diagnosisFailure: lost })
    await bootstrapAndCreate(fixture)
    const user = userEvent.setup()
    await user.click(await screen.findByRole("button", { name: "Diagnose scenario" }))

    expect(await screen.findByText("demo_session_lost")).toBeVisible()
    expect(screen.getByText("Request request-lost-001")).toBeVisible()
    expect(screen.getByRole("button", { name: "Reset session context" })).toBeVisible()
    expect(document.body).not.toHaveTextContent("demo-token-secret")
    expect(sessionValues()).not.toContain("scenario-001")
  })
})
