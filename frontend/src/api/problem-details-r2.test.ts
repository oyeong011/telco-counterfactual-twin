import { describe, expect, it } from "vitest"
import { ProblemDetailsSchema } from "../contracts/generated"
import { patch, scenario, session } from "../state/workflow-fixtures"
import { createApiClient, sessionAuthFromResponse } from "./client"
import { IdempotencyKeySchema } from "./idempotency"

describe("backend patch rejection problems", () => {
  it.each([
    "scenario-binding-mismatch",
    "baseline-hash-mismatch",
    "duplicate-patch-target",
    "unknown-patch-target",
    "target-kind-mismatch",
    "operation-target-mismatch",
    "unsupported-patch-parameters",
    "patch-parameter-type",
    "patch-parameter-range",
    "blast-radius-exceeded",
  ] as const)("accepts backend patch rejection code %s", (code) => {
    expect(
      ProblemDetailsSchema.safeParse({
        type: `https://telco-twin.invalid/problems/${code}`,
        title: "Patch rejected",
        status: 422,
        code,
        detail: "The typed patch is not valid for this scenario baseline.",
        request_id: "request-patch-code-r2",
      }).success,
    ).toBe(true)
  })

  it("preserves unsupported-patch-parameters and a matching response request id", async () => {
    const client = createApiClient({
      fetch: async () =>
        new Response(
          JSON.stringify({
            type: "https://telco-twin.invalid/problems/unsupported-patch-parameters",
            title: "Patch rejected",
            status: 422,
            code: "unsupported-patch-parameters",
            detail: "The typed patch is not valid for this scenario baseline.",
            request_id: "request-body-001",
          }),
          {
            status: 422,
            headers: {
              "content-type": "application/problem+json",
              "X-Request-Id": "request-body-001",
            },
          },
        ),
    })

    const result = await client.proposePatch(
      sessionAuthFromResponse(session),
      IdempotencyKeySchema.parse("idem-invalid-patch-r2"),
      scenario.scenario.scenario_id,
      patch.patch,
    )

    expect(result).toEqual({
      ok: false,
      problem: {
        type: "https://telco-twin.invalid/problems/unsupported-patch-parameters",
        title: "Patch rejected",
        status: 422,
        code: "unsupported-patch-parameters",
        detail: "The typed patch is not valid for this scenario baseline.",
        request_id: "request-body-001",
      },
      requestId: "request-body-001",
    })
  })
})
