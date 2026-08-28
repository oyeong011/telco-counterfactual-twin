import { describe, expect, it } from "vitest"
import {
  ApprovalRequestResponseSchema,
  Base64SignatureSchema,
  DemoSessionRequestSchema,
  Ed25519JwkSchema,
  EventSchema,
  NonceSchema,
  ProblemDetailsSchema,
  ScenarioResponseSchema,
  ServiceBuildInfoSchema,
  SimulationReadResponseSchema,
  UiBuildInfoSchema,
  UtcTimestampSchema,
} from "./generated"

const HASH = "a".repeat(64)
const SHA = "b".repeat(40)
const POLICY_HASH = "f670bd90d43b6f6d648ec72a367d7ea51e503d3b497e2cb54a6b0c6851440a4d"

const scenarioResponse = {
  scenario: {
    schema_version: "1.0",
    scenario_id: "scenario-001",
    topology_id: "topology-001",
    seed: 6701,
    fault_family: "radio-congestion",
    starts_at: "2026-08-28T00:00:00Z",
    duration_seconds: 300,
    target_ids: ["cell-0001"],
    parameters: {},
  },
  topology_hash: HASH,
  scenario_hash: HASH,
  run_id: "run-001",
}

const approvalRequestResponse = {
  approval_request: {
    request_id: "approval-request-001",
    session_id: "session-001",
    patch_hash: HASH,
    simulation_hash: HASH,
    policy_hash: POLICY_HASH,
    nonce: "A".repeat(22),
    requested_at: "2026-08-28T00:00:00Z",
    expires_at: "2026-08-28T00:01:00Z",
    state: "pending",
    schema_version: "1.0",
  },
  policy: {
    eligible: true,
    reasons: [],
    patch_hash: HASH,
    simulation_hash: HASH,
    quality_hash: HASH,
    policy_definition_hash: HASH,
    policy_hash: POLICY_HASH,
  },
  run_id: "run-001",
  evidence_id: "evidence-001",
}

describe("external contract parsers", () => {
  it("accepts a valid linked scenario response", () => {
    // Given: one response at the HTTP trust boundary.
    // When: the body is parsed with the closed response schema.
    const parsed = ScenarioResponseSchema.safeParse(scenarioResponse)

    // Then: the linked scenario and run identities remain available.
    expect(parsed.success).toBe(true)
    if (parsed.success) {
      expect(parsed.data.scenario.scenario_id).toBe("scenario-001")
      expect(parsed.data.run_id).toBe("run-001")
    }
  })

  it("rejects unknown response fields instead of widening the boundary", () => {
    // Given: a response carrying an unsupported top-level field.
    const malformed = { ...scenarioResponse, unexpected: "untrusted" }

    // When: the malformed body is parsed.
    const parsed = ScenarioResponseSchema.safeParse(malformed)

    // Then: the parser rejects it.
    expect(parsed.success).toBe(false)
  })

  it("keeps simulation comparison result nullable before comparison", () => {
    // Given: the server's pre-comparison simulation projection.
    const body = {
      simulation: {
        simulation_id: "simulation-001",
        scenario_id: "scenario-001",
        patch_id: "patch-001",
        run_id: "run-001",
        status: "completed",
        trace_hash: HASH,
      },
      result: null,
    }

    // When: the projection is parsed.
    const parsed = SimulationReadResponseSchema.safeParse(body)

    // Then: null remains an honest absence of comparison data.
    expect(parsed.success).toBe(true)
    if (parsed.success) expect(parsed.data.result).toBeNull()
  })

  it("parses structured problems and rejects malformed event payloads", () => {
    // Given: one stable problem and one event with an invalid schema version.
    const problem = {
      type: "https://telco-twin.invalid/problems/demo_token_expired",
      title: "Demo token expired",
      status: 401,
      code: "demo_token_expired",
      detail: "The demo token has expired.",
      request_id: "request-001",
    }
    const event = {
      schema_version: "9.9",
      event_id: "event-001",
      scenario_id: "scenario-001",
      timestamp: "2026-08-28T00:00:00Z",
      priority: 0,
      sequence_id: 0,
      event_type: "scenario-created",
      payload: {},
    }

    // When: both external values cross their parsers.
    const parsedProblem = ProblemDetailsSchema.safeParse(problem)
    const parsedEvent = EventSchema.safeParse(event)

    // Then: only the contract-conforming value is accepted.
    expect(parsedProblem.success).toBe(true)
    expect(parsedEvent.success).toBe(false)
  })

  it("enforces synthetic-only bootstrap and approval policy response shape", () => {
    // Given: a non-synthetic bootstrap and a valid approval response.
    const unsafeBootstrap = DemoSessionRequestSchema.safeParse({ synthetic_only: false })
    const approval = ApprovalRequestResponseSchema.safeParse(approvalRequestResponse)

    // When / Then: bootstrap cannot opt out and policy stays explicit.
    expect(unsafeBootstrap.success).toBe(false)
    expect(approval.success).toBe(true)
  })

  it("parses service and UI build identity contracts", () => {
    // Given: build identities with independently verifiable hashes.
    const service = {
      schema_version: "1.0",
      service_name: "telco-twin-api",
      version: "0.1.0",
      runtime_source_commit_sha: SHA,
      release_commit_sha: SHA,
      runtime_tree_hash: HASH,
      schema_hashes: { scenario: HASH },
      mcp_hash: HASH,
      policy_hash: HASH,
      trusted_root_hashes: HASH,
      built_at: "2026-08-28T00:00:00Z",
      image_digest: `sha256:${HASH}`,
      digest_scope: "local",
    }
    const ui = {
      schema_version: "1.0",
      service_name: "telco-twin-console",
      version: "0.1.0",
      runtime_source_commit_sha: SHA,
      release_commit_sha: SHA,
      runtime_tree_hash: HASH,
      schema_hashes: { scenario: HASH },
      mcp_hash: HASH,
      policy_hash: HASH,
      trusted_root_hashes: HASH,
      built_at: "2026-08-28T00:00:00Z",
      asset_manifest_hash: HASH,
    }

    // When: each identity is parsed.
    const parsedService = ServiceBuildInfoSchema.safeParse(service)
    const parsedUi = UiBuildInfoSchema.safeParse(ui)

    // Then: both build identities remain typed and usable.
    expect(parsedService.success).toBe(true)
    expect(parsedUi.success).toBe(true)
  })

  it("rejects unsafe dynamic keys and impossible UTC dates", () => {
    // Given: untrusted metadata that resembles an authority field and a normalized invalid date.
    const unsafe = ScenarioResponseSchema.safeParse({
      ...scenarioResponse,
      scenario: { ...scenarioResponse.scenario, parameters: { execute_action: "unexpected" } },
    })
    const impossibleDate = UtcTimestampSchema.safeParse("2026-02-31T00:00:00Z")

    // When / Then: both boundary violations are rejected.
    expect(unsafe.success).toBe(false)
    expect(impossibleDate.success).toBe(false)
  })

  it("rejects non-canonical base64url key material at the contract boundary", () => {
    // Given: correctly sized strings with altered trailing base64 bits.
    const nonce = `A${"A".repeat(20)}B`
    const signature = `A${"A".repeat(84)}B`
    const jwk = { kty: "OKP", crv: "Ed25519", x: `A${"A".repeat(41)}B` }

    // When: approval key material crosses the parser.
    const parsedNonce = NonceSchema.safeParse(nonce)
    const parsedSignature = Base64SignatureSchema.safeParse(signature)
    const parsedJwk = Ed25519JwkSchema.safeParse(jwk)

    // Then: length alone cannot bypass the backend's canonical byte-length rule.
    expect(parsedNonce.success).toBe(false)
    expect(parsedSignature.success).toBe(false)
    expect(parsedJwk.success).toBe(false)
  })
})
