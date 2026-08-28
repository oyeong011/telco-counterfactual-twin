import { canonicalJson } from "../contracts/canonical-json"
import type { ApprovalProof, EvidenceResponse } from "../contracts/generated"

export async function approvalProofHash(proof: ApprovalProof): Promise<string> {
  const bytes = new TextEncoder().encode(canonicalJson(proof))
  const digest = await globalThis.crypto.subtle.digest("SHA-256", bytes)
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("")
}

export async function evidenceProofHashMatches(response: EvidenceResponse): Promise<boolean> {
  const proof = response.approval_proof
  const claimedHash = response.evidence_card.approval_proof_hash
  if (proof === null) return claimedHash === null
  if (claimedHash === null) return false
  return (await approvalProofHash(proof)) === claimedHash
}
