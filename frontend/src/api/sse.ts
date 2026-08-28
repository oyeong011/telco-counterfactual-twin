import {
  type ApiFailure,
  type ContractId,
  ContractIdSchema,
  type Event,
  EventSchema,
  type EventType,
  EventTypeSchema,
} from "../contracts/generated"
import { type DemoToken, DemoTokenSchema } from "./auth"
import {
  ContractParseError,
  failureFromProblem,
  parseProblemResponse,
  transportFailure,
} from "./errors"

export type SseFrame = {
  readonly id: ContractId
  readonly event: EventType
  readonly data: Event
}

export type SseStreamOptions = {
  readonly baseUrl?: string
  readonly sessionToken: DemoToken
  readonly runId: ContractId
  readonly lastEventId?: ContractId
  readonly fetch?: typeof fetch
  readonly signal?: AbortSignal
}

export const SSE_TIMEOUT_MS = 10_000

export class SseProtocolError extends Error {
  override readonly name = "SseProtocolError"
}

type MutableFrame = {
  id?: string
  event?: string
  data: string[]
}

function emptyFrame(): MutableFrame {
  return { data: [] }
}

function parseField(line: string, frame: MutableFrame): void {
  if (line.startsWith(":")) return
  const separator = line.indexOf(":")
  const field = separator < 0 ? line : line.slice(0, separator)
  const rawValue = separator < 0 ? "" : line.slice(separator + 1)
  const value = rawValue.startsWith(" ") ? rawValue.slice(1) : rawValue
  switch (field) {
    case "id":
      frame.id = value
      return
    case "event":
      frame.event = value
      return
    case "data":
      frame.data.push(value)
      return
    case "retry":
      return
    default:
      return
  }
}

function completeFrame(frame: MutableFrame): SseFrame | null {
  if (frame.id === undefined && frame.event === undefined && frame.data.length === 0) return null
  if (frame.id === undefined || frame.event === undefined || frame.data.length === 0) {
    throw new SseProtocolError("SSE frame is missing id, event, or data")
  }
  const id = ContractIdSchema.safeParse(frame.id)
  const event = EventTypeSchema.safeParse(frame.event)
  if (!id.success || !event.success) throw new SseProtocolError("SSE frame identity is invalid")
  let payload: unknown
  try {
    payload = JSON.parse(frame.data.join("\n"))
  } catch (error) {
    if (error instanceof SyntaxError) throw new SseProtocolError("SSE data is not valid JSON")
    throw error
  }
  const parsed = EventSchema.safeParse(payload)
  if (!parsed.success) throw new ContractParseError("SSE event violates the public contract")
  if (parsed.data.event_id !== id.data || parsed.data.event_type !== event.data) {
    throw new SseProtocolError("SSE frame metadata does not match event data")
  }
  return { id: id.data, event: event.data, data: parsed.data }
}

async function* readSseBody(body: ReadableStream<Uint8Array>): AsyncGenerator<SseFrame> {
  const reader = body.getReader()
  const decoder = new TextDecoder()
  let buffer = ""
  let frame = emptyFrame()
  try {
    for (;;) {
      const chunk = await reader.read()
      if (chunk.done) break
      buffer += decoder.decode(chunk.value, { stream: true })
      const lines = buffer.split(/\r?\n/)
      buffer = lines.pop() ?? ""
      for (const line of lines) {
        if (line === "") {
          const completed = completeFrame(frame)
          if (completed) yield completed
          frame = emptyFrame()
        } else {
          parseField(line, frame)
        }
      }
    }
    buffer += decoder.decode()
    if (buffer !== "") parseField(buffer, frame)
    const completed = completeFrame(frame)
    if (completed) yield completed
  } finally {
    reader.releaseLock()
  }
}

export async function* streamRunEvents(
  options: SseStreamOptions,
): AsyncGenerator<SseFrame | ApiFailure> {
  const { VITE_API_BASE_URL } = import.meta.env
  const baseUrl = options.baseUrl ?? VITE_API_BASE_URL ?? ""
  const url = `${baseUrl.replace(/\/$/, "")}/api/runs/${options.runId}/events`
  const headers = new Headers({
    Accept: "text/event-stream",
    "X-Demo-Session-Token": DemoTokenSchema.parse(options.sessionToken),
  })
  if (options.lastEventId) headers.set("Last-Event-ID", options.lastEventId)
  let response: Response
  try {
    const signal = options.signal ?? AbortSignal.timeout(SSE_TIMEOUT_MS)
    const requestInit: RequestInit = { method: "GET", headers, signal }
    response = await (options.fetch ?? fetch)(url, requestInit)
  } catch (error) {
    if (error instanceof TypeError) {
      yield transportFailure()
      return
    }
    throw error
  }
  if (!response.ok) {
    yield failureFromProblem(await parseProblemResponse(response))
    return
  }
  if (!response.body) throw new SseProtocolError("SSE response has no readable body")
  yield* readSseBody(response.body)
}

export async function collectSseFrames(
  stream: AsyncIterable<SseFrame | ApiFailure>,
): Promise<readonly (SseFrame | ApiFailure)[]> {
  const frames: (SseFrame | ApiFailure)[] = []
  for await (const frame of stream) frames.push(frame)
  return frames
}
