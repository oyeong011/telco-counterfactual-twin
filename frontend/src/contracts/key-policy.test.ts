import { spawnSync } from "node:child_process"
import { describe, expect, it } from "vitest"
import { z } from "zod"
import { SafeKeySchema, UtcTimestampSchema } from "./generated"

const KEY_CORPUS = [
  "commandment-count",
  "duration-ms",
  "shellfish-count",
  "tokenization-mode",
  "apiary_count",
  "rapid_api_key",
  "apikey",
  "accesskey",
  "subscriber_identifier",
  "executeplan",
  "applynetwork",
] as const

const PYTHON_PARITY_PROGRAM = `
import json
import sys
from telco_twin.domain._contract import validate_safe_key

values = json.loads(sys.stdin.read())
result = {}
for value in values:
    try:
        validate_safe_key(value)
    except ValueError:
        result[value] = False
    else:
        result[value] = True
print(json.dumps(result, sort_keys=True))
`
const VerdictsSchema = z.record(z.string(), z.boolean())

class BackendParityError extends Error {
  override readonly name = "BackendParityError"
}

function backendKeyVerdicts(): Readonly<Record<string, boolean>> {
  const processResult = spawnSync(
    "uv",
    ["run", "--project", "../backend", "python", "-c", PYTHON_PARITY_PROGRAM],
    { cwd: process.cwd(), input: JSON.stringify(KEY_CORPUS), encoding: "utf8" },
  )
  if (processResult.status !== 0) {
    throw new BackendParityError(processResult.stderr || "backend key parity process failed")
  }
  return VerdictsSchema.parse(JSON.parse(processResult.stdout))
}

describe("backend scalar parity", () => {
  const backend = backendKeyVerdicts()

  it.each(KEY_CORPUS)("matches the live Python verdict for %s", (value) => {
    // Given: the verdict produced by the checked-in Python validator for this exact key.
    const backendVerdict = backend[value]

    // When: the independent TypeScript parser evaluates the same key.
    const frontendVerdict = SafeKeySchema.safeParse(value).success

    // Then: both runtime boundaries agree.
    expect(frontendVerdict).toBe(backendVerdict)
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
