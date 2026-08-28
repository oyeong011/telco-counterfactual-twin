import { afterEach, describe, expect, it } from "vitest"
import { type ApiFailure, ContractIdSchema } from "../contracts/generated"
import { DemoTokenSchema } from "./client"
import { type SseFrame, streamRunEvents } from "./sse"

const OPTIONS = {
  baseUrl: "https://api.example.test",
  sessionToken: DemoTokenSchema.parse("demo-token-secret"),
  runId: ContractIdSchema.parse("run-001"),
} as const

const event = (id: string, sequenceId: number) => ({
  schema_version: "1.0",
  event_id: id,
  scenario_id: "scenario-001",
  timestamp: "2026-08-28T00:00:00Z",
  priority: 0,
  sequence_id: sequenceId,
  event_type: "scenario-created",
  payload: { resource_id: "scenario-001", run_id: "run-001", status: "recorded" },
})

function streamResponse(chunks: readonly string[]): Response {
  const encoder = new TextEncoder()
  return new Response(
    new ReadableStream<Uint8Array>({
      start(controller) {
        for (const chunk of chunks) controller.enqueue(encoder.encode(chunk))
        controller.close()
      },
    }),
    { headers: { "content-type": "text/event-stream" } },
  )
}

async function collect(
  stream: AsyncIterable<SseFrame | ApiFailure>,
): Promise<readonly (SseFrame | ApiFailure)[]> {
  const frames: (SseFrame | ApiFailure)[] = []
  for await (const frame of stream) frames.push(frame)
  return frames
}

afterEach(() => window.history.replaceState({}, "", "/"))

describe("fetch-based finite SSE replay", () => {
  it("parses split frames and ignores heartbeat comments", async () => {
    // Given: two frames split across arbitrary byte chunks.
    const first = event("event-001", 0)
    const second = event("event-002", 1)
    const wire = [
      `id: event-001\nevent: scenario-created\ndata: ${JSON.stringify(first).slice(0, 35)}`,
      `${JSON.stringify(first).slice(35)}\n\n: heartbeat\n\n`,
      `id: event-002\nevent: scenario-created\ndata: ${JSON.stringify(second)}\n\n`,
    ]
    const fetcher: typeof fetch = async () => streamResponse(wire)

    // When: the response is consumed.
    const frames = await collect(streamRunEvents({ ...OPTIONS, fetch: fetcher }))

    // Then: both server events survive and comments do not become frames.
    expect(frames).toHaveLength(2)
    expect(frames.map((frame) => ("data" in frame ? frame.id : "failure"))).toEqual([
      "event-001",
      "event-002",
    ])
  })

  it("sends demo auth and Last-Event-ID on reconnect", async () => {
    // Given: a reconnect cursor and a wire recorder.
    let request: Request | undefined
    const fetcher: typeof fetch = async (input, init) => {
      request = new Request(input, init)
      return streamResponse([])
    }

    // When: the run stream opens with a cursor.
    await collect(
      streamRunEvents({
        ...OPTIONS,
        lastEventId: ContractIdSchema.parse("event-000"),
        fetch: fetcher,
      }),
    )

    // Then: the required custom auth and replay headers are present.
    expect(request?.headers.get("X-Demo-Session-Token")).toBe("demo-token-secret")
    expect(request?.headers.get("Last-Event-ID")).toBe("event-000")
    expect(request?.headers.get("Accept")).toBe("text/event-stream")
  })

  it("roots the default SSE URL from a nested browser route", async () => {
    // Given: no explicit API base and a client-side run detail path.
    window.history.pushState({}, "", "/runs/run-001")
    let request: Request | undefined
    const fetcher: typeof fetch = async (input, init) => {
      request = new Request(input, init)
      return streamResponse([])
    }

    // When: the same-origin stream opens.
    await collect(
      streamRunEvents({
        sessionToken: OPTIONS.sessionToken,
        runId: OPTIONS.runId,
        fetch: fetcher,
      }),
    )

    // Then: routing never makes the API page-relative under /runs/.
    expect(request && new URL(request.url).pathname).toBe("/api/runs/run-001/events")
  })

  it.each([
    [409, "sse_replay_gap"],
    [409, "sse_cursor_wrong_stream"],
  ])("surfaces server problem %s as %s", async (status, code) => {
    // Given: one structured server-side replay failure.
    const fetcher: typeof fetch = async () =>
      new Response(
        JSON.stringify({
          type: `https://telco-twin.invalid/problems/${code}`,
          title: code,
          status,
          code,
          detail: "safe detail",
          request_id: "request-001",
        }),
        {
          status,
          headers: { "content-type": "application/problem+json", "x-request-id": "request-001" },
        },
      )

    // When: the stream is consumed.
    const frames = await collect(streamRunEvents({ ...OPTIONS, fetch: fetcher }))

    // Then: the exact machine code is preserved.
    const first = frames[0]
    expect(first && "ok" in first ? first.problem.code : undefined).toBe(code)
  })

  it("rejects frame metadata that differs from the event body", async () => {
    // Given: an event whose outer and inner identifiers disagree.
    const payload = event("event-001", 0)
    const fetcher: typeof fetch = async () =>
      streamResponse([
        `id: event-002\nevent: scenario-created\ndata: ${JSON.stringify(payload)}\n\n`,
      ])

    // When: the frame crosses the parser boundary.
    const frames = await collect(streamRunEvents({ ...OPTIONS, fetch: fetcher }))

    // Then: the mismatch is a structured contract failure.
    const first = frames[0]
    expect(first && "ok" in first ? first.problem.code : undefined).toBe("client_contract_error")
  })
})
