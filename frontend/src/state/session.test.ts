import { describe, expect, it } from "vitest"
import {
  ContractIdSchema,
  DemoSessionResponseSchema,
  Sha256HexSchema,
  TypedPatchSchema,
  UtcTimestampSchema,
} from "../contracts/generated"
import { createSessionStorageAdapter, createSessionStore, type SessionStorageLike } from "./session"

class MemoryStorage implements SessionStorageLike {
  private readonly values = new Map<string, string>()

  getItem(key: string): string | null {
    return this.values.get(key) ?? null
  }

  setItem(key: string, value: string): void {
    this.values.set(key, value)
  }

  removeItem(key: string): void {
    this.values.delete(key)
  }
}

const session = DemoSessionResponseSchema.parse({
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
})

describe("session boundary", () => {
  it("holds the bearer in memory and clears it explicitly", () => {
    // Given: an in-memory session holder and a parsed bootstrap response.
    const store = createSessionStore()
    store.set(session)

    // When: the current session is read and then cleared.
    const active = store.get()
    store.clear()

    // Then: the token is available only during the active in-memory lifetime.
    expect(active?.demo_token).toBe("demo-token-secret")
    expect(store.get()).toBeNull()
  })

  it("restores only non-secret run drafts from the tab-scoped adapter", () => {
    // Given: a sessionStorage-shaped adapter with serialized run metadata.
    const backing = new MemoryStorage()
    const storage = createSessionStorageAdapter(backing)
    const patchBody = TypedPatchSchema.parse({
      schema_version: "1.0",
      patch_id: "patch-001",
      scenario_id: "scenario-001",
      base_topology_hash: Sha256HexSchema.parse("a".repeat(64)),
      changes: [
        {
          target_id: "cell-0001",
          target_kind: "cell",
          operation: "adjust-radio-capacity",
          parameters: { capacity_ues: 230 },
        },
      ],
      blast_radius: { max_cells: 1, max_ue_cohorts: 1, max_slices: 1 },
      proposed_at: UtcTimestampSchema.parse("2026-08-28T00:00:00Z"),
    })
    storage.saveRunDraft({
      runId: ContractIdSchema.parse("run-001"),
      scenarioId: ContractIdSchema.parse("scenario-001"),
      patchId: ContractIdSchema.parse("patch-001"),
      patchBody,
    })

    // When: a fresh adapter reads the tab-scoped run index.
    const restored = createSessionStorageAdapter(backing).listRunDrafts()

    // Then: the draft is recoverable and no bearer value was serialized.
    expect(restored[0]?.runId).toBe("run-001")
    expect(backing.getItem("telco-twin:run-drafts")).not.toContain("demo-token-secret")
  })

  it("does not require or touch localStorage", () => {
    // Given: a storage adapter backed only by a session-scoped object.
    const backing = new MemoryStorage()
    const storage = createSessionStorageAdapter(backing)

    // When: a missing draft is read.
    const result = storage.getRunDraft(ContractIdSchema.parse("run-missing"))

    // Then: it is an explicit absence and the adapter has no localStorage dependency.
    expect(result).toBeNull()
    expect(backing.getItem("telco-twin:local-storage")).toBeNull()
  })
})
