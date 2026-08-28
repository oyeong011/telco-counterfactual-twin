import { describe, expect, it, vi } from "vitest"
import { generateIdempotencyKey, IdempotencyKeySchema } from "./idempotency"

describe("idempotency keys", () => {
  it("generates a contract-safe key from crypto.randomUUID", () => {
    // Given: a deterministic UUID source for this unit boundary.
    const randomUuid = vi.spyOn(globalThis.crypto, "randomUUID")
    randomUuid.mockReturnValue("01234567-89ab-4cde-8fab-0123456789ab")

    // When: a caller requests a new mutation key.
    const key = generateIdempotencyKey()

    // Then: crypto was used and the prefixed key satisfies the identifier contract.
    expect(randomUuid).toHaveBeenCalledOnce()
    expect(IdempotencyKeySchema.safeParse(key).success).toBe(true)
    expect(key.startsWith("idem-")).toBe(true)
    randomUuid.mockRestore()
  })

  it("rejects empty and malformed caller-supplied keys", () => {
    // Given: values that cannot identify one mutation safely.
    // When: each value crosses the idempotency boundary.
    const empty = IdempotencyKeySchema.safeParse("")
    const malformed = IdempotencyKeySchema.safeParse("1-not-a-contract-id")

    // Then: neither is accepted.
    expect(empty.success).toBe(false)
    expect(malformed.success).toBe(false)
  })
})
