import { z } from "zod"
import { ID_PATTERN } from "../contracts/generated"

export const IdempotencyKeySchema = z
  .string()
  .min(3)
  .max(96)
  .regex(ID_PATTERN)
  .brand<"IdempotencyKey">()
export type IdempotencyKey = z.infer<typeof IdempotencyKeySchema>

export function generateIdempotencyKey(): IdempotencyKey {
  return IdempotencyKeySchema.parse(`idem-${globalThis.crypto.randomUUID()}`)
}
