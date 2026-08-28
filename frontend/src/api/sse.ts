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
  contractFailure,
  failureFromProblem,
  networkFailure,
  parseProblemResponse,
  requestAbortedFailure,
  timeoutFailure,
} from "./errors"
import { apiPath, resolveApiBaseUrl } from "./url"

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
const SSE_MAX_FRAME_BYTES = 64 * 1024

export class SseProtocolError extends Error {
  override readonly name = "SseProtocolError"
}

type MutableFrame = {
  id?: string
  event?: string
  data: string[]
  size: number
}

function emptyFrame(): MutableFrame {
  return { data: [], size: 0 }
}

function parseField(line: string, frame: MutableFrame): void {
  frame.size += new TextEncoder().encode(line).byteLength + 1
  if (frame.size > SSE_MAX_FRAME_BYTES) throw new SseProtocolError("SSE frame exceeds size limit")
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
      if (buffer.length > SSE_MAX_FRAME_BYTES)
        throw new SseProtocolError("SSE frame exceeds size limit")
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

type StreamControl = {
  readonly signal: AbortSignal
  readonly timedOut: () => boolean
  readonly callerAborted: () => boolean
  readonly abort: () => void
  readonly dispose: () => void
}

function createStreamControl(callerSignal: AbortSignal | undefined): StreamControl {
  const controller = new AbortController()
  let didTimeout = false
  let didCallerAbort = false
  const timeoutId = setTimeout(() => {
    didTimeout = true
    controller.abort()
  }, SSE_TIMEOUT_MS)
  const abortFromCaller = (): void => {
    didCallerAbort = true
    controller.abort()
  }
  if (callerSignal) {
    if (callerSignal.aborted) abortFromCaller()
    else callerSignal.addEventListener("abort", abortFromCaller, { once: true })
  }
  return {
    signal: controller.signal,
    timedOut: () => didTimeout,
    callerAborted: () => didCallerAbort,
    abort: () => controller.abort(),
    dispose: () => {
      clearTimeout(timeoutId)
      callerSignal?.removeEventListener("abort", abortFromCaller)
    },
  }
}

function streamFailure(error: unknown, control: StreamControl): ApiFailure {
  const errorName =
    error instanceof DOMException ? error.name : error instanceof Error ? error.name : ""
  if (control.callerAborted()) return requestAbortedFailure()
  if (control.timedOut() || errorName === "TimeoutError") return timeoutFailure()
  if (error instanceof TypeError || errorName === "NetworkError" || errorName === "AbortError")
    return networkFailure()
  return contractFailure()
}

export async function* streamRunEvents(
  options: SseStreamOptions,
): AsyncGenerator<SseFrame | ApiFailure> {
  const baseUrl = resolveApiBaseUrl(options.baseUrl)
  const url = apiPath(baseUrl, `api/runs/${options.runId}/events`)
  const headers = new Headers({
    Accept: "text/event-stream",
    "X-Demo-Session-Token": DemoTokenSchema.parse(options.sessionToken),
  })
  if (options.lastEventId) headers.set("Last-Event-ID", options.lastEventId)
  const control = createStreamControl(options.signal)
  let response: Response
  try {
    const requestInit: RequestInit = { method: "GET", headers, signal: control.signal }
    response = await (options.fetch ?? fetch)(url, requestInit)
  } catch (error) {
    if (error instanceof Error || error instanceof DOMException) yield streamFailure(error, control)
    else yield contractFailure()
    control.dispose()
    return
  }
  if (!response.ok) {
    try {
      yield failureFromProblem(await parseProblemResponse(response))
    } catch (error) {
      control.abort()
      if (error instanceof Error || error instanceof DOMException)
        yield streamFailure(error, control)
      else yield contractFailure()
    } finally {
      control.dispose()
    }
    return
  }
  const contentType = response.headers.get("content-type")?.split(";", 1)[0]?.trim().toLowerCase()
  if (contentType !== "text/event-stream") {
    yield contractFailure()
    control.dispose()
    return
  }
  if (!response.body) {
    yield contractFailure()
    control.dispose()
    return
  }
  try {
    yield* readSseBody(response.body)
  } catch (error) {
    control.abort()
    if (error instanceof Error || error instanceof DOMException) yield streamFailure(error, control)
    else yield contractFailure()
  } finally {
    control.dispose()
  }
}
