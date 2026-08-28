import type { SessionAuth } from "../api/auth"
import type { ApiClient } from "../api/client"
import type { ApiFailure, ContractId, Event } from "../contracts/generated"

export type ReplayResult =
  | { readonly ok: true; readonly events: readonly Event[] }
  | { readonly ok: false; readonly failure: ApiFailure }

export async function replayRunEvents(
  client: ApiClient,
  session: SessionAuth,
  runId: ContractId,
): Promise<ReplayResult> {
  const events: Event[] = []
  for await (const frame of client.streamRunEvents(session, runId)) {
    if ("ok" in frame && !frame.ok) return { ok: false, failure: frame }
    if ("data" in frame) events.push(frame.data)
  }
  return { ok: true, events }
}
