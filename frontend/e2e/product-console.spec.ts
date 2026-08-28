import AxeBuilder from "@axe-core/playwright"
import { expect, type Page, type Route, test } from "@playwright/test"
import { canonicalSha256 } from "../src/contracts/canonical-json"
import {
  ApprovalDecisionResponseSchema,
  EventSchema,
  EvidenceResponseSchema,
  TypedPatchSchema,
} from "../src/contracts/generated"
import {
  approval,
  comparison,
  diagnosis,
  HASHES,
  patch,
  scenario,
  session,
  simulation,
} from "../src/state/workflow-fixtures"

const BROWSER_ORIGIN = "http://localhost:4173"

type RouteState = {
  readonly idempotencyKeys: string[]
  submittedPatch: typeof patch.patch
}

function json(route: Route, body: unknown, status = 200): Promise<void> {
  return route.fulfill({
    status,
    contentType: "application/json",
    headers: {
      "X-Request-Id": `request-e2e-${status}`,
      "Access-Control-Allow-Origin": BROWSER_ORIGIN,
      "Access-Control-Expose-Headers": "Idempotency-Replayed, X-Request-Id",
    },
    body: JSON.stringify(body),
  })
}

function rejectionDecision() {
  return ApprovalDecisionResponseSchema.parse({
    state: "rejected",
    approval_proof: {
      proof_id: "approval-proof-001",
      approval_request_id: approval.approval_request.request_id,
      session_id: session.session_id,
      session_key_id: session.session_certificate.session_key_id,
      patch_hash: HASHES.patch,
      simulation_hash: HASHES.simulation,
      policy_hash: HASHES.policy,
      nonce: approval.approval_request.nonce,
      decision: "rejected",
      approved_at: approval.approval_request.requested_at,
      expires_at: approval.approval_request.expires_at,
      certificate_hash: HASHES.certificate,
      proof_signature: "A".repeat(86),
      schema_version: "1.0",
    },
    effect: "evidence-only",
  })
}

function evidenceFor(submittedPatchId: string) {
  const proof = rejectionDecision().approval_proof
  const eventTypes = [
    ["scenario-created", "scenario-001"],
    ["scenario-diagnosed", "diagnosis-001"],
    ["patch-proposed", submittedPatchId],
    ["simulation-completed", "simulation-001"],
    ["comparison-created", "comparison-001"],
    ["approval-requested", "approval-request-001"],
    ["approval-rejected", "approval-proof-001"],
  ] as const
  const events = eventTypes.map(([eventType, resourceId], sequenceId) =>
    EventSchema.parse({
      schema_version: "1.0",
      event_id: `event-00${sequenceId + 1}`,
      scenario_id: scenario.scenario.scenario_id,
      timestamp: `2026-08-28T00:00:0${sequenceId}Z`,
      priority: 0,
      sequence_id: sequenceId,
      event_type: eventType,
      payload: {
        request_hash: HASHES.constraint,
        resource_id: resourceId,
        run_id: scenario.run_id,
        status: "recorded",
      },
    }),
  )
  return EvidenceResponseSchema.parse({
    run_id: scenario.run_id,
    evidence_card: {
      schema_version: "1.0",
      evidence_id: approval.evidence_id,
      session_id: session.session_id,
      scenario_hash: HASHES.scenario,
      patch_hash: HASHES.patch,
      simulation_hash: HASHES.simulation,
      policy_hash: HASHES.policy,
      approval_proof_hash: canonicalSha256(proof),
      seed: scenario.scenario.seed,
      source_commit_sha: "b".repeat(40),
      contract_hashes: { scenario: HASHES.scenario },
      generated_at: "2026-08-28T00:00:06Z",
    },
    events,
    approval_proof: proof,
  })
}

async function installApi(page: Page, state: RouteState): Promise<void> {
  await page.route("**/api/**", async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    if (!path.startsWith("/api/")) return route.continue()
    if (request.method() === "OPTIONS")
      return route.fulfill({
        status: 204,
        headers: {
          "Access-Control-Allow-Origin": BROWSER_ORIGIN,
          "Access-Control-Allow-Methods": "GET, POST",
          "Access-Control-Allow-Headers": "Content-Type, Idempotency-Key, X-Demo-Session-Token",
        },
      })
    const key = request.headers()["idempotency-key"]
    if (key) state.idempotencyKeys.push(key)
    if (path === "/api/demo-sessions") return json(route, session, 201)
    if (path === "/api/scenarios" && request.method() === "GET") return json(route, { items: [] })
    if (path === "/api/scenarios") return json(route, scenario, 201)
    if (path.endsWith("/diagnose")) return json(route, diagnosis)
    if (path.endsWith("/patches")) {
      state.submittedPatch = TypedPatchSchema.parse(request.postDataJSON())
      return json(route, { ...patch, patch: state.submittedPatch }, 201)
    }
    if (path.endsWith("/simulations"))
      return json(route, { ...simulation, patch_id: state.submittedPatch.patch_id }, 201)
    if (path.endsWith("/comparisons")) return json(route, comparison, 201)
    if (path.endsWith("/approval-requests")) return json(route, approval, 201)
    if (path.endsWith("/reject")) return json(route, rejectionDecision())
    if (path.endsWith("/evidence")) return json(route, evidenceFor(state.submittedPatch.patch_id))
    return json(
      route,
      {
        type: "https://telco-twin.invalid/problems/route_not_found",
        title: "Route not found",
        status: 404,
        code: "route_not_found",
        detail: "The E2E test did not register this contract route.",
        request_id: "request-e2e-404",
      },
      404,
    )
  })
}

test("completes a rejected evidence-only lifecycle through the production UI", async ({ page }) => {
  const state: RouteState = { idempotencyKeys: [], submittedPatch: patch.patch }
  await installApi(page, state)
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.goto("/")

  for (const label of [
    "Start synthetic session",
    "Create scenario",
    "Diagnose scenario",
    "Validate and propose patch",
    "Simulate candidate",
    "Compare evidence",
    "Request approval evidence",
    "Record rejection evidence",
    "Load evidence package",
  ]) {
    await page.getByRole("button", { name: label }).click()
  }

  await expect(page.getByText("Evidence package received", { exact: true })).toBeVisible()
  await expect(page.getByText(/Browser signature verification is not performed/)).toBeVisible()
  await expect(page.getByText("Evidence package verified")).toHaveCount(0)
  await expect(
    page.getByText("Approval records evidence only. It never executes a patch."),
  ).toBeVisible()
  expect(new Set(state.idempotencyKeys).size).toBe(7)
  expect(state.idempotencyKeys).toHaveLength(7)
  expect(
    await page.evaluate(() =>
      Array.from({ length: sessionStorage.length }, (_, index) =>
        sessionStorage.getItem(sessionStorage.key(index) ?? ""),
      ).join(""),
    ),
  ).not.toContain("demo-token-secret")
  await page.getByRole("link", { name: "Evidence", exact: true }).click()
  const eventTable = page.getByRole("table", { name: "Evidence event ledger" })
  await expect(eventTable).toBeVisible()
  expect(await eventTable.getByRole("row").count()).toBe(8)
  expect(
    (await new AxeBuilder({ page }).analyze()).violations.filter(
      (item) => item.impact === "serious" || item.impact === "critical",
    ),
  ).toEqual([])
})

test("keeps a mobile deep link isolated when no token exists in memory", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 })
  await page.goto("/runs/run-001")
  await expect(page.getByText("Session context missing")).toBeVisible()
  await expect(page.getByText(/in-memory session token/)).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  expect(await page.getByRole("navigation", { name: "Primary" }).getByRole("link").count()).toBe(5)
})
