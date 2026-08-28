import { describe, expect, it } from "vitest"
import { parseBenchmarkForm, parseScenarioForm } from "./form-inputs"

describe("numeric form boundaries", () => {
  it.each(["", "1.5", "-1", "9007199254740992"])(
    "rejects scenario seed %j before the API boundary",
    (seed) => {
      expect(parseScenarioForm("radio-congestion", seed)).toEqual({
        ok: false,
        issue: "Seed must be a whole number between 0 and 9007199254740991.",
      })
    },
  )

  it.each(["", "2.5", "1", "26"])(
    "rejects benchmark iterations %j before the API boundary",
    (iterations) => {
      expect(parseBenchmarkForm("6701", iterations)).toEqual({
        ok: false,
        issue: "Iterations must be a whole number between 2 and 25.",
      })
    },
  )

  it("returns parsed whole-number requests", () => {
    expect(parseScenarioForm("radio-congestion", "42")).toEqual({
      ok: true,
      value: { fault_family: "radio-congestion", seed: 42 },
    })
    expect(parseBenchmarkForm("42", "5")).toEqual({
      ok: true,
      value: { seed: 42, iterations: 5 },
    })
  })
})
