import { describe, expect, it } from "vitest"
import { canonicalSha256 } from "./canonical-json"
import { PolicyEvaluationSchema, RootDescriptorSchema } from "./generated"

const POLICY_HASH = "04c32a734d8cd8cc28829d6772b29a992da121aa9499922c9c1181195297bdeb"
const ROOT_HASH = "44f56f0d1028d26c50f4bc143ccc6de5dddceb06fd9ec952628c70ca86d42145"

const policy = {
  eligible: true,
  reasons: [],
  patch_hash: "3".repeat(64),
  simulation_hash: "aac0582bfebc773af393d0a6acf3f3c3b1d50d34f87ec9fc2274b6d8b98374f6",
  quality_hash: "a".repeat(64),
  policy_definition_hash: "b".repeat(64),
  policy_hash: POLICY_HASH,
}

const root = {
  root_key_id: "root-key-001",
  algorithm: "Ed25519",
  public_key_jwk: { kty: "OKP", crv: "Ed25519", x: "A".repeat(43) },
  environment: "test",
  not_before: "2026-08-28T00:00:00Z",
  not_after: "2027-08-28T00:00:00Z",
  descriptor_hash: ROOT_HASH,
  schema_version: "1.0",
}

describe("backend semantic hash parity", () => {
  it("matches Python RFC 8785 SHA-256 fixtures", () => {
    // Given: the exact Python policy and root hash preimages.
    const { policy_hash: _policyHash, ...policyBody } = policy
    const { descriptor_hash: _rootHash, ...rootBody } = root

    // When: the browser-side canonical digests are computed.
    const policyDigest = canonicalSha256(policyBody)
    const rootDigest = canonicalSha256(rootBody)

    // Then: both match independently generated backend values.
    expect(policyDigest).toBe(POLICY_HASH)
    expect(rootDigest).toBe(ROOT_HASH)
  })

  it("matches backend model hashing when response fields contain explicit null", () => {
    // Given: an ineligible policy whose nullable provenance is excluded by Pydantic.
    const responseShape = {
      eligible: false,
      reasons: ["simulation-missing"],
      patch_hash: null,
      simulation_hash: null,
      quality_hash: "a".repeat(64),
      policy_definition_hash: "b".repeat(64),
      policy_hash: "bb850e1a2ed38ef24d9b4be7c604a25cfac061e078ea3a38076ab173ba4a1b2c",
    }
    const {
      patch_hash: _patchHash,
      policy_hash: expected,
      simulation_hash: _simulationHash,
      ...body
    } = responseShape

    // When / Then: model hashing removes null object fields like exclude_none=True.
    expect(canonicalSha256(body)).toBe(expected)
    expect(PolicyEvaluationSchema.safeParse(responseShape).success).toBe(true)
  })

  it("rejects structurally valid policy and root objects with forged hashes", () => {
    // Given: valid shapes whose claimed digests do not match their bodies.
    const forgedPolicy = { ...policy, policy_hash: "0".repeat(64) }
    const forgedRoot = { ...root, descriptor_hash: "0".repeat(64) }

    // When: both objects cross their public schemas.
    const parsedPolicy = PolicyEvaluationSchema.safeParse(forgedPolicy)
    const parsedRoot = RootDescriptorSchema.safeParse(forgedRoot)

    // Then: shape alone cannot establish semantic integrity.
    expect(parsedPolicy.success).toBe(false)
    expect(parsedRoot.success).toBe(false)
  })
})
