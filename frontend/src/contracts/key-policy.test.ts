import { describe, expect, it } from "vitest"
import { SafeKeySchema, UtcTimestampSchema } from "./generated"

describe("backend scalar parity", () => {
  it.each([
    ["commandment-count", true],
    ["duration-ms", true],
    ["shellfish-count", true],
    ["tokenization-mode", true],
    ["apiary_count", true],
    ["rapid_api_key", false],
    ["apikey", false],
    ["accesskey", false],
    ["subscriber_identifier", false],
    ["executeplan", false],
    ["applynetwork", false],
  ])("matches backend safe-key verdict for %s", (value, expected) => {
    // Given / When: one independently enumerated backend parity fixture is parsed.
    const parsed = SafeKeySchema.safeParse(value)

    // Then: normalized whitelists and unsafe lexeme groups match the Python contract.
    expect(parsed.success).toBe(expected)
  })

  it.each([
    ["0001-01-01T00:00:00Z", true],
    ["2028-02-29T23:59:59Z", true],
    ["0000-01-01T00:00:00Z", false],
    ["2027-02-29T00:00:00Z", false],
    ["2026-04-31T00:00:00Z", false],
  ])("matches backend UTC-second verdict for %s", (value, expected) => {
    // Given / When: a boundary timestamp is parsed.
    const parsed = UtcTimestampSchema.safeParse(value)

    // Then: only real Python-datetime-compatible UTC seconds survive.
    expect(parsed.success).toBe(expected)
  })
})
