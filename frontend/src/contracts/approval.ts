import { z } from "zod"
import { canonicalSha256Without } from "./canonical-json"
import {
  ApprovalDecisionSchema,
  ApprovalEvidenceStateSchema,
  BASE64URL_PATTERN,
  ContractIdSchema,
  EnvironmentSchema,
  SchemaVersionSchema,
  Sha256HexSchema,
  UtcTimestampSchema,
} from "./primitives"
import { PolicyEvaluationSchema } from "./simulation"

const strictObject = <T extends z.ZodRawShape>(shape: T) => z.object(shape).strict()
function decodeBase64Url(value: string): Uint8Array | null {
  if (BASE64URL_PATTERN.test(value) === false) return null
  try {
    const padded = value.replace(/-/g, "+").replace(/_/g, "/")
    const binary = atob(padded + "=".repeat((4 - (padded.length % 4)) % 4))
    const decoded = Uint8Array.from(binary, (character) => character.charCodeAt(0))
    const canonical = btoa(String.fromCharCode(...decoded))
      .replace(/\+/g, "-")
      .replace(/\//g, "_")
      .replace(/=+$/, "")
    return canonical === value ? decoded : null
  } catch (error) {
    if (error instanceof DOMException || error instanceof TypeError) return null
    throw error
  }
}

function hasDecodedLength(value: string, bytes: number): boolean {
  return decodeBase64Url(value)?.byteLength === bytes
}

export const NonceSchema = z
  .string()
  .length(22)
  .regex(/^[A-Za-z0-9_-]{22}$/)
  .refine((value) => hasDecodedLength(value, 16))
  .brand<"Nonce128">()
export type Nonce = z.infer<typeof NonceSchema>
export const Base64SignatureSchema = z
  .string()
  .length(86)
  .regex(/^[A-Za-z0-9_-]{86}$/)
  .refine((value) => hasDecodedLength(value, 64))
  .brand<"Ed25519Signature">()
export type Base64Signature = z.infer<typeof Base64SignatureSchema>

export const Ed25519JwkSchema = strictObject({
  kty: z.literal("OKP"),
  crv: z.literal("Ed25519"),
  x: z
    .string()
    .length(43)
    .regex(/^[A-Za-z0-9_-]{43}$/)
    .refine((value) => hasDecodedLength(value, 32)),
})
export type Ed25519Jwk = z.infer<typeof Ed25519JwkSchema>

function exactWindow(
  value: { readonly start: string; readonly end: string },
  message: string,
  context: z.RefinementCtx,
): void {
  if (Date.parse(value.end) - Date.parse(value.start) !== 60_000)
    context.addIssue({ code: "custom", message })
}

export const ApprovalRequestSchema = strictObject({
  request_id: ContractIdSchema,
  session_id: ContractIdSchema,
  patch_hash: Sha256HexSchema,
  simulation_hash: Sha256HexSchema,
  policy_hash: Sha256HexSchema,
  nonce: NonceSchema,
  requested_at: UtcTimestampSchema,
  expires_at: UtcTimestampSchema,
  state: z.literal("pending"),
  schema_version: SchemaVersionSchema,
}).superRefine((value, context) =>
  exactWindow(
    { start: value.requested_at, end: value.expires_at },
    "approval window must be exactly 60 seconds",
    context,
  ),
)
export type ApprovalRequest = z.infer<typeof ApprovalRequestSchema>

export const SessionKeyCertificateSchema = strictObject({
  session_id: ContractIdSchema,
  session_key_id: ContractIdSchema,
  session_public_key_jwk: Ed25519JwkSchema,
  root_key_id: ContractIdSchema,
  issued_at: UtcTimestampSchema,
  expires_at: UtcTimestampSchema,
  environment: EnvironmentSchema,
  certificate_signature: Base64SignatureSchema,
  schema_version: SchemaVersionSchema,
}).superRefine((value, context) =>
  exactWindow(
    { start: value.issued_at, end: value.expires_at },
    "certificate window must be exactly 60 seconds",
    context,
  ),
)
export type SessionKeyCertificate = z.infer<typeof SessionKeyCertificateSchema>

export const ApprovalProofSchema = strictObject({
  proof_id: ContractIdSchema,
  approval_request_id: ContractIdSchema,
  session_id: ContractIdSchema,
  session_key_id: ContractIdSchema,
  patch_hash: Sha256HexSchema,
  simulation_hash: Sha256HexSchema,
  policy_hash: Sha256HexSchema,
  nonce: NonceSchema,
  decision: ApprovalDecisionSchema,
  approved_at: UtcTimestampSchema,
  expires_at: UtcTimestampSchema,
  certificate_hash: Sha256HexSchema,
  proof_signature: Base64SignatureSchema,
  schema_version: SchemaVersionSchema,
}).superRefine((value, context) =>
  exactWindow(
    { start: value.approved_at, end: value.expires_at },
    "proof window must be exactly 60 seconds",
    context,
  ),
)
export type ApprovalProof = z.infer<typeof ApprovalProofSchema>

export const ApprovalRequestResponseSchema = strictObject({
  approval_request: ApprovalRequestSchema,
  policy: PolicyEvaluationSchema,
  run_id: ContractIdSchema,
  evidence_id: ContractIdSchema,
})
export type ApprovalRequestResponse = z.infer<typeof ApprovalRequestResponseSchema>

export const ApprovalReadResponseSchema = strictObject({
  approval_request: ApprovalRequestSchema,
  state: ApprovalEvidenceStateSchema,
  proof_hash: Sha256HexSchema.nullable(),
})
export type ApprovalReadResponse = z.infer<typeof ApprovalReadResponseSchema>

export const ApprovalDecisionResponseSchema = strictObject({
  state: ApprovalEvidenceStateSchema,
  approval_proof: ApprovalProofSchema,
  effect: z.literal("evidence-only"),
})
export type ApprovalDecisionResponse = z.infer<typeof ApprovalDecisionResponseSchema>

export const RootDescriptorSchema = strictObject({
  root_key_id: ContractIdSchema,
  algorithm: z.literal("Ed25519"),
  public_key_jwk: Ed25519JwkSchema,
  environment: EnvironmentSchema,
  not_before: UtcTimestampSchema,
  not_after: UtcTimestampSchema,
  descriptor_hash: Sha256HexSchema,
  schema_version: SchemaVersionSchema,
}).superRefine((value, context) => {
  if (Date.parse(value.not_after) <= Date.parse(value.not_before))
    context.addIssue({ code: "custom", message: "root validity window is empty" })
  if (canonicalSha256Without(value, "descriptor_hash") !== value.descriptor_hash)
    context.addIssue({ code: "custom", message: "root descriptor hash mismatch" })
})
export type RootDescriptor = z.infer<typeof RootDescriptorSchema>
