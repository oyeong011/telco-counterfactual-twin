import { z } from "zod"
import type { ContractIdSchema, DemoSessionResponse } from "../contracts/generated"

export const DemoTokenSchema = z.string().min(1).brand<"DemoToken">()
export type DemoToken = z.infer<typeof DemoTokenSchema>

export const JwtTokenSchema = z.string().min(1).brand<"JwtToken">()
export type JwtToken = z.infer<typeof JwtTokenSchema>

export type SessionAuth = {
  readonly sessionId: z.infer<typeof ContractIdSchema>
  readonly demoToken: DemoToken
}

export function sessionAuthFromResponse(session: DemoSessionResponse): SessionAuth {
  return {
    sessionId: session.session_id,
    demoToken: DemoTokenSchema.parse(session.demo_token),
  }
}
