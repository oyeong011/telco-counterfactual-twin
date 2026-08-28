import { expect, type Page, type Response, test } from "@playwright/test"
import {
  DemoSessionResponseSchema,
  EvidenceResponseSchema,
  ProblemDetailsSchema,
  ScenarioResponseSchema,
} from "../src/contracts/generated"

const API_BASE = "http://127.0.0.1:18080"
const BROWSER_ORIGIN = "http://localhost:4173"

type ObservedMutation = {
  readonly response: Response
  readonly idempotencyKey: string
}

async function clickForResponse(
  page: Page,
  label: string,
  matches: (pathname: string) => boolean,
  expectedStatus: number,
  mutation = true,
  expectedMethod: "GET" | "POST" = "POST",
): Promise<ObservedMutation> {
  const [response] = await Promise.all([
    page.waitForResponse((candidate) => {
      const pathname = new URL(candidate.url()).pathname
      return matches(pathname) && candidate.request().method() === expectedMethod
    }),
    page.getByRole("button", { name: label }).click(),
  ])
  expect(response.status()).toBe(expectedStatus)
  const responseHeaders = await response.allHeaders()
  expect(responseHeaders["x-request-id"]).toMatch(/^request-/)
  const requestHeaders = await response.request().allHeaders()
  const idempotencyKey = requestHeaders["idempotency-key"] ?? ""
  if (mutation) expect(idempotencyKey).toMatch(/^idem-/)
  else expect(idempotencyKey).toBe("")
  return { response, idempotencyKey }
}

test("real FastAPI lifecycle returns bound evidence and finite SSE", async ({ page }) => {
  await page.goto("/")
  const idempotencyKeys: string[] = []

  await clickForResponse(
    page,
    "Start synthetic session",
    (path) => path === "/api/demo-sessions",
    201,
    false,
  )
  const scenarioMutation = await clickForResponse(
    page,
    "Create scenario",
    (path) => path === "/api/scenarios",
    201,
  )
  idempotencyKeys.push(scenarioMutation.idempotencyKey)
  idempotencyKeys.push(
    (await clickForResponse(page, "Diagnose scenario", (path) => path.endsWith("/diagnose"), 200))
      .idempotencyKey,
  )
  const patchMutation = await clickForResponse(
    page,
    "Validate and propose patch",
    (path) => path.endsWith("/patches"),
    201,
  )
  idempotencyKeys.push(patchMutation.idempotencyKey)
  expect(patchMutation.response.request().postDataJSON()).toMatchObject({
    changes: [
      {
        target_kind: "cell",
        operation: "adjust-radio-capacity",
        parameters: { capacity_ues: 230 },
      },
    ],
  })
  for (const step of [
    ["Simulate candidate", "/simulations", 201],
    ["Compare evidence", "/comparisons", 201],
    ["Request approval evidence", "/approval-requests", 201],
    ["Record rejection evidence", "/reject", 200],
  ] as const) {
    idempotencyKeys.push(
      (await clickForResponse(page, step[0], (path) => path.endsWith(step[1]), step[2]))
        .idempotencyKey,
    )
  }
  const evidenceRead = await clickForResponse(
    page,
    "Load evidence package",
    (path) => path.endsWith("/evidence"),
    200,
    false,
    "GET",
  )
  const evidence = EvidenceResponseSchema.parse(await evidenceRead.response.json())
  expect(evidence.events).toHaveLength(7)
  expect(evidence.approval_proof?.decision).toBe("rejected")
  const replay = await clickForResponse(
    page,
    "Replay current events",
    (path) => path.endsWith("/events"),
    200,
    false,
    "GET",
  )
  expect((await replay.response.allHeaders())["content-type"]).toContain("text/event-stream")
  const replayBody = await replay.response.text()
  expect(replayBody).toContain("event: scenario-created")
  expect(replayBody).toContain("event: approval-rejected")
  expect(new Set(idempotencyKeys).size).toBe(7)
  expect(idempotencyKeys).toHaveLength(7)
  await expect(page.getByText("Evidence package received", { exact: true })).toBeVisible()
  await expect(page.getByText(/Browser signature verification is not performed/)).toBeVisible()
  await expect(page.getByText("Evidence package verified")).toHaveCount(0)

  await page.getByRole("link", { name: "Evidence", exact: true }).click()
  await expect(page.getByRole("heading", { level: 1, name: "Evidence board" })).toBeVisible()
  await expect(page.locator("main")).toBeFocused()
  expect(await page.title()).toBe("Evidence board · Telco Counterfactual Twin Console")
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: "Download evidence JSON" }).click(),
  ])
  expect(download.suggestedFilename()).toMatch(/^evidence-.*\.json$/)
  expect(await download.failure()).toBeNull()
})

test("real FastAPI preserves unsupported patch parameters and request identity", async ({
  request,
}) => {
  const bootstrap = await request.post(`${API_BASE}/api/demo-sessions`, {
    headers: { Origin: BROWSER_ORIGIN },
    data: { synthetic_only: true },
  })
  expect(bootstrap.status()).toBe(201)
  const session = DemoSessionResponseSchema.parse(await bootstrap.json())
  const scenarioResponse = await request.post(`${API_BASE}/api/scenarios`, {
    headers: {
      Origin: BROWSER_ORIGIN,
      "X-Demo-Session-Token": session.demo_token,
      "Idempotency-Key": "idem-live-invalid-scenario-r2",
    },
    data: { fault_family: "radio-congestion", seed: 6701 },
  })
  const scenario = ScenarioResponseSchema.parse(await scenarioResponse.json())
  const invalid = await request.post(
    `${API_BASE}/api/scenarios/${scenario.scenario.scenario_id}/patches`,
    {
      headers: {
        Origin: BROWSER_ORIGIN,
        "X-Demo-Session-Token": session.demo_token,
        "Idempotency-Key": "idem-live-invalid-patch-r2",
      },
      data: {
        schema_version: "1.0",
        patch_id: "patch-live-invalid-r2",
        scenario_id: scenario.scenario.scenario_id,
        base_topology_hash: scenario.topology_hash,
        changes: [
          {
            target_id: scenario.scenario.target_ids[0],
            target_kind: "cell",
            operation: "adjust-radio-capacity",
            parameters: {},
          },
        ],
        blast_radius: { max_cells: 1, max_ue_cohorts: 1, max_slices: 1 },
        proposed_at: scenario.scenario.starts_at,
      },
    },
  )

  expect(invalid.status()).toBe(422)
  const requestId = invalid.headers()["x-request-id"]
  expect(requestId).toMatch(/^request-/)
  const problem = ProblemDetailsSchema.parse(await invalid.json())
  expect(problem.code).toBe("unsupported-patch-parameters")
  expect(problem.request_id).toBe(requestId)
  expect(problem.detail).toBe("The typed patch is not valid for this scenario baseline.")
})
