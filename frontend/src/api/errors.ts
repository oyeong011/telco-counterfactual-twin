import { z } from "zod"
import { type ApiFailure, type ProblemDetails, ProblemDetailsSchema } from "../contracts/generated"

export type SessionProblemClass =
  | "expired"
  | "invalid"
  | "not_found"
  | "lost"
  | "unavailable"
  | "none"

export class ContractParseError extends Error {
  override readonly name = "ContractParseError"
}

export type ParsedProblem = {
  readonly problem: ProblemDetails
  readonly requestId: string
}

export async function parseProblemResponse(response: Response): Promise<ParsedProblem> {
  let body: unknown
  try {
    body = await response.json()
  } catch (error) {
    if (error instanceof SyntaxError) {
      throw new ContractParseError("problem response is not valid JSON", { cause: error })
    }
    throw error
  }

  try {
    const problem = ProblemDetailsSchema.parse(body)
    const requestId = response.headers.get("X-Request-Id") ?? problem.request_id
    return { problem, requestId }
  } catch (error) {
    if (error instanceof z.ZodError) {
      throw new ContractParseError("problem response violates the public contract", {
        cause: error,
      })
    }
    throw error
  }
}

export function failureFromProblem(parsed: ParsedProblem): ApiFailure {
  return {
    ok: false,
    problem: parsed.problem,
    requestId: parsed.requestId,
  }
}

export function classifySessionProblem(problem: ProblemDetails): SessionProblemClass {
  switch (problem.code) {
    case "demo_token_expired":
      return "expired"
    case "demo_token_required":
    case "demo_token_invalid":
      return "invalid"
    case "demo_session_not_found":
      return "not_found"
    case "demo_session_lost":
      return "lost"
    case "session_state_unavailable":
      return "unavailable"
    default:
      return "none"
  }
}

export type SessionGate = "missing" | Exclude<SessionProblemClass, "none">

export function sessionGateForProblem(problem: ProblemDetails): SessionGate | null {
  const classified = classifySessionProblem(problem)
  return classified === "none" ? null : classified
}

export function transportFailure(requestId = "client-transport"): ApiFailure {
  return {
    ok: false,
    problem: {
      type: "https://telco-twin.invalid/problems/client_transport_error",
      title: "Client transport error",
      status: 503,
      code: "client_transport_error",
      detail: "The service could not be reached. Retry the safe read or resubmit the mutation.",
      request_id: requestId,
    },
    requestId,
  }
}

export function requestAbortedFailure(requestId = "client-sse"): ApiFailure {
  return {
    ok: false,
    problem: {
      type: "https://telco-twin.invalid/problems/client_request_aborted",
      title: "Client request aborted",
      status: 499,
      code: "client_request_aborted",
      detail: "The client cancelled the request before the evidence stream completed.",
      request_id: requestId,
    },
    requestId,
  }
}

export function timeoutFailure(requestId = "client-sse-timeout"): ApiFailure {
  return {
    ok: false,
    problem: {
      type: "https://telco-twin.invalid/problems/client_timeout_error",
      title: "Client request timed out",
      status: 504,
      code: "client_timeout_error",
      detail: "The evidence stream did not complete within the client timeout.",
      request_id: requestId,
    },
    requestId,
  }
}

export function networkFailure(requestId = "client-sse-network"): ApiFailure {
  return {
    ok: false,
    problem: {
      type: "https://telco-twin.invalid/problems/client_network_error",
      title: "Client network error",
      status: 503,
      code: "client_network_error",
      detail: "The evidence stream could not reach the service.",
      request_id: requestId,
    },
    requestId,
  }
}

export function contractFailure(requestId = "client-contract"): ApiFailure {
  return {
    ok: false,
    problem: {
      type: "https://telco-twin.invalid/problems/client_contract_error",
      title: "Client contract error",
      status: 502,
      code: "client_contract_error",
      detail: "The service returned data outside the public contract.",
      request_id: requestId,
    },
    requestId,
  }
}
