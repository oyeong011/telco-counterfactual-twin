import { act, render } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { createConsoleApiFixture } from "../test/consoleApi"
import { ConsoleProvider, useConsole } from "./ConsoleContext"

type CapturedConsole = ReturnType<typeof useConsole>

describe("console mutation single flight", () => {
  it("coalesces concurrent diagnosis actions into one request and one key", async () => {
    let releaseDiagnosis = (): void => undefined
    const diagnosisGate = new Promise<void>((resolve) => {
      releaseDiagnosis = resolve
    })
    const fixture = createConsoleApiFixture({ diagnosisGate })
    let captured: CapturedConsole | null = null
    const Capture = () => {
      captured = useConsole()
      return null
    }
    render(
      <ConsoleProvider client={fixture.client}>
        <Capture />
      </ConsoleProvider>,
    )
    const current = (): CapturedConsole => {
      if (captured === null) throw new TypeError("console context was not captured")
      return captured
    }
    await act(() => current().actions.bootstrap())
    await act(() =>
      current().actions.createScenario({ fault_family: "radio-congestion", seed: 6701 }),
    )

    let first: Promise<void> = Promise.resolve()
    let second: Promise<void> = Promise.resolve()
    act(() => {
      first = current().actions.diagnose()
      second = current().actions.diagnose()
    })
    releaseDiagnosis()
    await act(() => Promise.all([first, second]))

    expect(fixture.callCounts.diagnosis).toBe(1)
    expect(fixture.idempotencyKeys).toHaveLength(2)
    expect(current().model.workflow.phase).toBe("diagnosis")
    expect(current().model.validationIssue).toBeNull()
  })
})
