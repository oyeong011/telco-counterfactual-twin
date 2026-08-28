import { describe, expect, it, vi } from "vitest"
import { type ApiFailure, ContractIdSchema } from "../contracts/generated"
import { DemoTokenSchema } from "./client"
import { SSE_TIMEOUT_MS, type SseFrame, streamRunEvents } from "./sse"

const OPTIONS = {
  baseUrl: "https://api.example.test",
  sessionToken: DemoTokenSchema.parse("demo-token-secret"),
  runId: ContractIdSchema.parse("run-001"),
} as const

async function collect(
  stream: AsyncIterable<SseFrame | ApiFailure>,
): Promise<readonly (SseFrame | ApiFailure)[]> {
  const frames: (SseFrame | ApiFailure)[] = []
  for await (const frame of stream) frames.push(frame)
  return frames
}

function failureCode(frames: readonly (SseFrame | ApiFailure)[]): string | undefined {
  const first = frames[0]
  return first && "ok" in first ? first.problem.code : undefined
}

describe("typed SSE transport failures", () => {
  it("normalizes an opening TimeoutError", async () => {
    // Given: the fetch boundary reports an explicit timeout.
    const fetcher: typeof fetch = async () => {
      throw new DOMException("timed out", "TimeoutError")
    }

    // When: the finite stream opens.
    const frames = await collect(streamRunEvents({ ...OPTIONS, fetch: fetcher }))

    // Then: timeout has its own typed recovery code.
    expect(failureCode(frames)).toBe("client_timeout_error")
  })

  it("normalizes the client-owned timeout when opening never completes", async () => {
    // Given: a fetch implementation that rejects only when its request signal aborts.
    vi.useFakeTimers()
    try {
      const fetcher: typeof fetch = async (_input, init) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener(
            "abort",
            () => reject(new DOMException("timed out", "AbortError")),
            { once: true },
          )
        })

      // When: the bounded client timer elapses.
      const pending = collect(streamRunEvents({ ...OPTIONS, fetch: fetcher }))
      await vi.advanceTimersByTimeAsync(SSE_TIMEOUT_MS)
      const frames = await pending

      // Then: timeout remains distinct from caller cancellation.
      expect(failureCode(frames)).toBe("client_timeout_error")
    } finally {
      vi.useRealTimers()
    }
  })

  it("keeps explicit caller cancellation distinct", async () => {
    // Given: a caller-owned signal connected to the actual request signal.
    const caller = new AbortController()
    const fetcher: typeof fetch = async (_input, init) =>
      new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener(
          "abort",
          () => reject(new DOMException("caller aborted", "AbortError")),
          { once: true },
        )
      })

    // When: the caller cancels the in-flight stream.
    const pending = collect(streamRunEvents({ ...OPTIONS, signal: caller.signal, fetch: fetcher }))
    caller.abort()
    const frames = await pending

    // Then: cancellation is not mislabeled as timeout or network outage.
    expect(failureCode(frames)).toBe("client_request_aborted")
  })

  it("normalizes a reader timeout after headers arrive", async () => {
    // Given: a valid SSE response whose body reader times out.
    const body = new ReadableStream<Uint8Array>({
      pull(controller) {
        controller.error(new DOMException("timed out", "TimeoutError"))
      },
    })
    const fetcher: typeof fetch = async () =>
      new Response(body, { status: 200, headers: { "content-type": "text/event-stream" } })

    // When: body consumption begins.
    const frames = await collect(streamRunEvents({ ...OPTIONS, fetch: fetcher }))

    // Then: body timeouts use the same typed timeout path.
    expect(failureCode(frames)).toBe("client_timeout_error")
  })

  it("keeps a network failure distinct", async () => {
    // Given: the browser cannot establish the network request.
    const fetcher: typeof fetch = async () => {
      throw new TypeError("network unavailable")
    }

    // When: the finite stream opens.
    const frames = await collect(streamRunEvents({ ...OPTIONS, fetch: fetcher }))

    // Then: callers can render a network-specific recovery state.
    expect(failureCode(frames)).toBe("client_network_error")
  })

  it("rejects a successful non-SSE response as a contract failure", async () => {
    // Given: HTTP 200 with a text body instead of event-stream framing.
    const fetcher: typeof fetch = async () =>
      new Response("not an event stream", { headers: { "content-type": "text/plain" } })

    // When: the stream opens.
    const frames = await collect(streamRunEvents({ ...OPTIONS, fetch: fetcher }))

    // Then: arbitrary text is never treated as evidence.
    expect(failureCode(frames)).toBe("client_contract_error")
  })

  it("bounds oversized frames before JSON parsing", async () => {
    // Given: a single frame larger than the parser budget.
    const oversized = `id: event-001\nevent: scenario-created\ndata: ${"x".repeat(70_000)}\n\n`
    const encoder = new TextEncoder()
    const fetcher: typeof fetch = async () =>
      new Response(
        new ReadableStream<Uint8Array>({
          start(controller) {
            controller.enqueue(encoder.encode(oversized))
            controller.close()
          },
        }),
        { headers: { "content-type": "text/event-stream" } },
      )

    // When: the frame is consumed.
    const frames = await collect(streamRunEvents({ ...OPTIONS, fetch: fetcher }))

    // Then: the parser yields one bounded contract failure.
    expect(failureCode(frames)).toBe("client_contract_error")
  })
})
