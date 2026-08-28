import { describe, expect, it } from "vitest"
import { classifySessionProblem, parseProblemResponse, type SessionProblemClass } from "./errors"

const problem = (status: number, code: string) => ({
  type: `https://telco-twin.invalid/problems/${code}`,
  title: code,
  status,
  code,
  detail: "safe detail",
  request_id: "request-001",
})

describe("API problem handling", () => {
  it.each([
    [401, "demo_token_expired", "expired"],
    [401, "demo_token_invalid", "invalid"],
    [404, "demo_session_not_found", "not_found"],
    [410, "demo_session_lost", "lost"],
    [503, "session_state_unavailable", "unavailable"],
  ] satisfies readonly [number, string, SessionProblemClass][])(
    "classifies %s %s as %s",
    async (status, code, expected) => {
      // Given: one structured session continuity problem.
      const response = new Response(JSON.stringify(problem(status, code)), {
        status,
        headers: {
          "content-type": "application/problem+json",
          "x-request-id": "request-001",
        },
      })

      // When: the HTTP body is parsed and classified.
      const parsed = await parseProblemResponse(response)

      // Then: the stable machine class is preserved.
      expect(parsed.problem.code).toBe(code)
      expect(classifySessionProblem(parsed.problem)).toBe(expected)
    },
  )

  it("rejects a problem body without the required request identifier", async () => {
    // Given: an HTTP error whose body violates the problem contract.
    const response = new Response(
      JSON.stringify({ ...problem(409, "idempotency_conflict"), request_id: "" }),
      {
        status: 409,
        headers: { "content-type": "application/problem+json" },
      },
    )

    // When / Then: parsing rejects the malformed boundary value.
    await expect(parseProblemResponse(response)).rejects.toThrow()
  })
})
