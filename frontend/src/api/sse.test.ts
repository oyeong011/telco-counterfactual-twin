import { describe, expect, it } from "vitest"
import { ContractIdSchema } from "../contracts/generated"
import { DemoTokenSchema } from "./client"
import { collectSseFrames, streamRunEvents } from "./sse"

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

const streamResponse = (chunks: readonly string[]) =>
  new Response(
    new ReadableStream<Uint8Array>({
      start(controller) {
        const encoder = new TextEncoder()
        for (const chunk of chunks) controller.enqueue(encoder.encode(chunk))
        controller.close()
      },
    }),
    { status: 200, headers: { "content-type": "text/event-stream" } },
  )

describe("fetch-based SSE replay", () => {
  it("parses split frames and heartbeat comments through fetch", async () => {
    // Given: one SSE response split across arbitrary chunks and a heartbeat comment.
    const first = event("event-001", 0)
    const second = event("event-002", 1)
    const wire = [
      `id: event-001\nevent: scenario-created\ndata: ${JSON.stringify(first).slice(0, 35)}`,
      `${JSON.stringify(first).slice(35)}\n\n: heartbeat\n\n`,
      `id: event-002\nevent: scenario-created\ndata: ${JSON.stringify(second)}\n\n`,
    ]
    const fetcher: typeof fetch = async () => streamResponse(wire)

    // When: the finite fetch stream is consumed.
    const frames = await collectSseFrames(
      streamRunEvents({
        baseUrl: "https://api.example.test",
        sessionToken: DemoTokenSchema.parse("demo-token-secret"),
        runId: ContractIdSchema.parse("run-001"),
        fetch: fetcher,
      }),
    )

    // Then: both real event IDs and payloads survive chunk parsing; comments are ignored.
    expect(frames).toHaveLength(2)
    const parsedFrames = frames.filter(
      (frame): frame is Exclude<typeof frame, { readonly ok: false }> => "data" in frame,
    )
    expect(parsedFrames.map((frame) => frame.id)).toEqual(["event-001", "event-002"])
    expect(parsedFrames[1]?.data.sequence_id).toBe(1)
  })

  it("sends demo auth and Last-Event-ID on reconnect", async () => {
    // Given: a reconnect cursor and a recorder at the fetch boundary.
    let request: Request | undefined
    const fetcher: typeof fetch = async (input, init) => {
      request = new Request(input, init)
      return streamResponse([])
    }

    // When: the run stream is opened with a cursor.
    await collectSseFrames(
      streamRunEvents({
        baseUrl: "https://api.example.test",
        sessionToken: DemoTokenSchema.parse("demo-token-secret"),
        runId: ContractIdSchema.parse("run-001"),
        lastEventId: ContractIdSchema.parse("event-000"),
        fetch: fetcher,
      }),
    )

    // Then: auth and resume are explicit request headers.
    expect(request).toBeDefined()
    if (request) {
      expect(request.headers.get("X-Demo-Session-Token")).toBe("demo-token-secret")
      expect(request.headers.get("Last-Event-ID")).toBe("event-000")
      expect(request.headers.get("Accept")).toBe("text/event-stream")
    }
  })

  it.each([
    [409, "sse_replay_gap"],
    [409, "sse_cursor_wrong_stream"],
  ])("surfaces bounded stream problem %s as %s", async (status, code) => {
    // Given: a structured server-side replay failure.
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
    const frames = await collectSseFrames(
      streamRunEvents({
        baseUrl: "https://api.example.test",
        sessionToken: DemoTokenSchema.parse("demo-token-secret"),
        runId: ContractIdSchema.parse("run-001"),
        fetch: fetcher,
      }),
    )

    // Then: the caller receives the exact machine code, not fabricated stream data.
    expect(frames).toHaveLength(1)
    const failure = frames[0]
    expect(failure && "ok" in failure && failure.ok).toBe(false)
    if (failure && "ok" in failure && !failure.ok) expect(failure.problem.code).toBe(code)
  })

  it("rejects an event whose stream id differs from its event payload id", async () => {
    // Given: an SSE frame with a mismatched external event identifier.
    const payload = event("event-001", 0)
    const fetcher: typeof fetch = async () =>
      streamResponse([
        `id: event-002\nevent: scenario-created\ndata: ${JSON.stringify(payload)}\n\n`,
      ])

    // When / Then: parsing fails closed at the stream boundary.
    await expect(
      collectSseFrames(
        streamRunEvents({
          baseUrl: "https://api.example.test",
          sessionToken: DemoTokenSchema.parse("demo-token-secret"),
          runId: ContractIdSchema.parse("run-001"),
          fetch: fetcher,
        }),
      ),
    ).rejects.toThrow()
  })
})
