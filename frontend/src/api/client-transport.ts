import { type KyInstance, NetworkError, type Options, TimeoutError } from "ky"
import { z } from "zod"
import type { ApiResult } from "../contracts/generated"
import {
  ContractParseError,
  failureFromProblem,
  parseProblemResponse,
  transportFailure,
} from "./errors"
import { type IdempotencyKey, IdempotencyKeySchema } from "./idempotency"

export const API_TIMEOUT_MS = 10_000
export const API_GET_RETRY_LIMIT = 1
const RETRYABLE_STATUS_CODES = [408, 429, 500, 502, 503, 504] as const

type RequestAuth = {
  readonly session?: { readonly demoToken: string }
  readonly jwt?: string
  readonly key?: IdempotencyKey
}

type BodySchema<T> = z.ZodType<T>

function isRetryableStatus(status: number): status is (typeof RETRYABLE_STATUS_CODES)[number] {
  return RETRYABLE_STATUS_CODES.some((candidate) => candidate === status)
}

function authHeaders(auth: RequestAuth): Headers {
  const headers = new Headers()
  if (auth.session) headers.set("X-Demo-Session-Token", auth.session.demoToken)
  if (auth.jwt) headers.set("Authorization", `Bearer ${auth.jwt}`)
  if (auth.key) headers.set("Idempotency-Key", auth.key)
  return headers
}

export type ApiTransport = {
  readonly request: <T>(
    method: "get" | "post",
    path: string,
    schema: BodySchema<T>,
    auth?: RequestAuth,
    body?: unknown,
    successStatuses?: readonly number[],
  ) => Promise<ApiResult<T>>
  readonly emptyBody: () => Record<string, never>
  readonly withKey: (key: IdempotencyKey) => IdempotencyKey
}

export function createApiTransport(http: KyInstance): ApiTransport {
  async function request<T>(
    method: "get" | "post",
    path: string,
    schema: BodySchema<T>,
    auth: RequestAuth = {},
    body?: unknown,
    successStatuses: readonly number[] = [200, 201],
  ): Promise<ApiResult<T>> {
    const requestOptions: Options = {
      method,
      headers: authHeaders(auth),
      retry:
        method === "get"
          ? { limit: API_GET_RETRY_LIMIT, methods: ["get"], delay: () => 0 }
          : { limit: 0, methods: [] },
    }
    for (let attempt = 0; attempt <= API_GET_RETRY_LIMIT; attempt += 1) {
      let response: Response
      try {
        response = await (body === undefined
          ? http(path, requestOptions)
          : http(path, { ...requestOptions, json: body }))
      } catch (error) {
        if (
          error instanceof TimeoutError ||
          error instanceof NetworkError ||
          error instanceof TypeError
        )
          return transportFailure()
        throw error
      }
      if (!successStatuses.includes(response.status)) {
        if (method === "get" && isRetryableStatus(response.status) && attempt < API_GET_RETRY_LIMIT)
          continue
        return failureFromProblem(await parseProblemResponse(response))
      }
      let payload: unknown
      try {
        payload = await response.json()
      } catch (error) {
        if (error instanceof SyntaxError)
          throw new ContractParseError("response body is not valid JSON", { cause: error })
        throw error
      }
      try {
        const data = schema.parse(payload)
        const requestId = response.headers.get("X-Request-Id")
        if (!requestId) throw new ContractParseError("response omitted X-Request-Id")
        return {
          ok: true,
          data,
          meta: { requestId, replayed: response.headers.get("Idempotency-Replayed") === "true" },
        }
      } catch (error) {
        if (error instanceof z.ZodError)
          throw new ContractParseError("response violates the public contract", { cause: error })
        throw error
      }
    }
    throw new ContractParseError("GET retry budget exhausted")
  }

  return { request, emptyBody: () => ({}), withKey: (key) => IdempotencyKeySchema.parse(key) }
}

export type { RequestAuth }
