import { afterEach, describe, expect, it } from "vitest"
import {
  ContractIdSchema,
  PolicyEvaluationSchema,
  SafeKeySchema,
  UtcTimestampSchema,
} from "../contracts/generated"
import { createApiClient, DemoTokenSchema } from "./client"
import { IdempotencyKeySchema } from "./idempotency"

const HASH = "a".repeat(64)
const SESSION = {
  sessionId: ContractIdSchema.parse("session-001"),
  demoToken: DemoTokenSchema.parse("demo-token-secret"),
}

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

const response = (body: unknown, status = 200, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", "x-request-id": "request-001", ...headers },
  })

afterEach(() => window.history.replaceState({}, "", "/"))

describe("HTTP API client", () => {
  it("uses backend-aligned semantic key and date guards at API boundaries", () => {
    // Given: values the backend's recursive contract rejects.
    const apiKey = SafeKeySchema.safeParse("apikey")
    const accessKey = SafeKeySchema.safeParse("accesskey")
    const yearZero = UtcTimestampSchema.safeParse("0000-01-01T00:00:00Z")
    const ineligible = PolicyEvaluationSchema.safeParse({
      eligible: true,
      reasons: ["unsafe-constraint"],
      patch_hash: null,
      simulation_hash: null,
      quality_hash: HASH,
      policy_definition_hash: HASH,
      policy_hash: HASH,
    })

    // When / Then: semantic, temporal, and eligibility violations reject at the boundary.
    expect(apiKey.success).toBe(false)
    expect(accessKey.success).toBe(false)
    expect(yearZero.success).toBe(false)
    expect(ineligible.success).toBe(false)
  })

  it("roots same-origin requests from a nested route when no API base is configured", async () => {
    // Given: a client without VITE_API_BASE_URL and a browser-like nested route.
    window.history.pushState({}, "", "/runs/run-001")
    const requests: Request[] = []
    const fetcher: typeof fetch = async (input, init) => {
      requests.push(new Request(input, init))
      return response({ items: [] })
    }
    const client = createApiClient({ fetch: fetcher })

    // When: a session-scoped read is issued from the default same-origin client.
    const result = await client.listScenarios(SESSION)

    // Then: the request pathname is API-rooted, never page-relative under /runs/.
    expect(result.ok).toBe(true)
    const request = requests[0]
    expect(request).toBeDefined()
    if (request) expect(new URL(request.url).pathname).toBe("/api/scenarios")
  })

  it("bootstraps synthetic-only and lets the browser provide Origin naturally", async () => {
    // Given: a wire-level fetch recorder returning a valid session body.
    const calls: Request[] = []
    const fetcher: typeof fetch = async (input, init) => {
      const request = new Request(input, init)
      calls.push(request)
      return response(
        {
          session_id: "session-001",
          demo_token: "demo-token-secret",
          session_certificate: {
            session_id: "session-001",
            session_key_id: "session-key-001",
            session_public_key_jwk: { kty: "OKP", crv: "Ed25519", x: "A".repeat(43) },
            root_key_id: "root-key-001",
            issued_at: "2026-08-28T00:00:00Z",
            expires_at: "2026-08-28T00:01:00Z",
            environment: "test",
            certificate_signature: "A".repeat(86),
            schema_version: "1.0",
          },
          expires_at: "2026-08-28T00:01:00Z",
          startup_epoch: "epoch-001",
          durability: "process-memory",
          synthetic_only: true,
        },
        201,
      )
    }
    const client = createApiClient({ baseUrl: "https://api.example.test", fetch: fetcher })

    // When: the unauthenticated bootstrap method runs.
    const result = await client.bootstrapDemoSession()

    // Then: only the required synthetic acknowledgement is posted and no manual Origin is set.
    expect(result.ok).toBe(true)
    const request = calls[0]
    expect(request).toBeDefined()
    if (request) {
      expect(request.url).toBe("https://api.example.test/api/demo-sessions")
      expect(await request.json()).toEqual({ synthetic_only: true })
      expect(request.headers.has("Idempotency-Key")).toBe(false)
      expect(request.headers.has("Origin")).toBe(false)
    }
  })

  it("parses response metadata and requires caller idempotency on mutations", async () => {
    // Given: a valid scenario wire response and a caller-owned mutation key.
    const calls: Request[] = []
    const fetcher: typeof fetch = async (input, init) => {
      calls.push(new Request(input, init))
      return response(scenarioResponse, 201, { "idempotency-replayed": "true" })
    }
    const client = createApiClient({ baseUrl: "https://api.example.test", fetch: fetcher })
    const parsedKey = IdempotencyKeySchema.parse("idem-scenario-001")

    // When: a session-scoped scenario mutation is submitted.
    const result = await client.createScenario(SESSION, parsedKey, {
      fault_family: "radio-congestion",
      seed: 6701,
    })

    // Then: auth, idempotency, path, and replay metadata are observable at the wire boundary.
    expect(result.ok).toBe(true)
    if (result.ok) expect(result.meta.replayed).toBe(true)
    const request = calls[0]
    expect(request).toBeDefined()
    if (request) {
      expect(request.method).toBe("POST")
      expect(request.headers.get("X-Demo-Session-Token")).toBe(SESSION.demoToken)
      expect(request.headers.get("Idempotency-Key")).toBe("idem-scenario-001")
      expect(await request.json()).toEqual({ fault_family: "radio-congestion", seed: 6701 })
    }
  })

  it("retries GET once but never retries a mutation after a network failure", async () => {
    // Given: a GET that recovers and a POST that fails on its first attempt.
    let getAttempts = 0
    let postAttempts = 0
    const fetcher: typeof fetch = async (input, init) => {
      const request = new Request(input, init)
      if (request.method === "GET") {
        getAttempts += 1
        if (getAttempts === 1) {
          return response(
            {
              type: "https://telco-twin.invalid/problems/session_state_unavailable",
              title: "Session unavailable",
              status: 503,
              code: "session_state_unavailable",
              detail: "safe detail",
              request_id: "request-001",
            },
            503,
          )
        }
        return response({ items: [] }, 200)
      }
      postAttempts += 1
      throw new TypeError("offline")
    }
    const client = createApiClient({ baseUrl: "https://api.example.test", fetch: fetcher })
    const key = IdempotencyKeySchema.parse("idem-scenario-retry")

    // When: the safe GET and mutation are attempted.
    const listed = await client.listScenarios(SESSION)
    const created = await client.createScenario(SESSION, key, {
      fault_family: "radio-congestion",
      seed: 6701,
    })

    // Then: GET retry is bounded while POST has exactly one attempt.
    expect(listed.ok).toBe(true)
    expect(getAttempts).toBe(2)
    expect(created.ok).toBe(false)
    expect(postAttempts).toBe(1)
  })

  it("does not include bearer material in transport failures", async () => {
    // Given: a network failure after a request carrying the opaque session token.
    const fetcher: typeof fetch = async () => {
      throw new TypeError("offline")
    }
    const client = createApiClient({ baseUrl: "https://api.example.test", fetch: fetcher })
    const key = IdempotencyKeySchema.parse("idem-scrub-001")

    // When: the mutation reports its transport failure.
    const result = await client.createScenario(SESSION, key, {
      fault_family: "radio-congestion",
      seed: 6701,
    })

    // Then: the failure is structured without echoing the token.
    expect(result.ok).toBe(false)
    expect(JSON.stringify(result)).not.toContain(SESSION.demoToken)
  })
})
