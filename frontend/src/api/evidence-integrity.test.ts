import { describe, expect, it } from "vitest"
import { ApprovalProofSchema, EvidenceResponseSchema } from "../contracts/generated"
import { approvalProofHash, evidenceProofHashMatches } from "./evidence-integrity"

const HASHES = {
  scenario: "2".repeat(64),
  patch: "3".repeat(64),
  simulation: "9".repeat(64),
  policy: "c".repeat(64),
  certificate: "d".repeat(64),
  proof: "4f8d9bd70bd33e928429697276a63a434e139683682e1ff70ae5ae697fad1759",
} as const

const proof = ApprovalProofSchema.parse({
  proof_id: "approval-proof-001",
  approval_request_id: "approval-request-001",
  session_id: "session-001",
  session_key_id: "session-key-001",
  patch_hash: HASHES.patch,
  simulation_hash: HASHES.simulation,
  policy_hash: HASHES.policy,
  nonce: "A".repeat(22),
  decision: "approved",
  approved_at: "2026-08-28T00:00:00Z",
  expires_at: "2026-08-28T00:01:00Z",
  certificate_hash: HASHES.certificate,
  proof_signature: "A".repeat(86),
  schema_version: "1.0",
})

const evidence = EvidenceResponseSchema.parse({
  run_id: "run-001",
  evidence_card: {
    schema_version: "1.0",
    evidence_id: "evidence-001",
    session_id: "session-001",
    scenario_hash: HASHES.scenario,
    patch_hash: HASHES.patch,
    simulation_hash: HASHES.simulation,
    policy_hash: HASHES.policy,
    approval_proof_hash: HASHES.proof,
    seed: 6701,
    source_commit_sha: "b".repeat(40),
    contract_hashes: { scenario: HASHES.scenario },
    generated_at: "2026-08-28T00:00:06Z",
  },
  events: [],
  approval_proof: proof,
})

describe("approval proof evidence integrity", () => {
  it("matches the backend RFC 8785 proof hash fixture", async () => {
    // Given / When: a parsed proof is hashed by the browser boundary.
    const hash = await approvalProofHash(proof)

    // Then: the result equals the independently generated Python backend hash.
    expect(hash).toBe(HASHES.proof)
  })

  it("rejects an evidence card whose proof hash is unrelated", async () => {
    // Given: a valid evidence shape with a different claimed proof hash.
    const mismatched = EvidenceResponseSchema.parse({
      ...evidence,
      evidence_card: { ...evidence.evidence_card, approval_proof_hash: "0".repeat(64) },
    })

    // When / Then: structural validity cannot replace content binding.
    await expect(evidenceProofHashMatches(mismatched)).resolves.toBe(false)
  })
})
