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
  if (problem.status === 401) {
    return problem.code === "demo_token_expired" ? "expired" : "invalid"
  }
  if (problem.status === 404 && problem.code === "demo_session_not_found") return "not_found"
  if (problem.status === 410 && problem.code === "demo_session_lost") return "lost"
  if (problem.status === 503) return "unavailable"
  return "none"
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
