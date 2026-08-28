import {
  type BenchmarkRequest,
  BenchmarkRequestSchema,
  type ScenarioCreateRequest,
  ScenarioCreateRequestSchema,
} from "../contracts/generated"

export type FormParseResult<T> =
  | { readonly ok: true; readonly value: T }
  | { readonly ok: false; readonly issue: string }

const SEED_ISSUE = "Seed must be a whole number between 0 and 9007199254740991."
const ITERATION_ISSUE = "Iterations must be a whole number between 2 and 25."

export function parseScenarioForm(
  faultFamily: string,
  seedInput: string,
): FormParseResult<ScenarioCreateRequest> {
  if (seedInput.trim() === "") return { ok: false, issue: SEED_ISSUE }
  const parsed = ScenarioCreateRequestSchema.safeParse({
    fault_family: faultFamily,
    seed: Number(seedInput),
  })
  return parsed.success ? { ok: true, value: parsed.data } : { ok: false, issue: SEED_ISSUE }
}

export function parseBenchmarkForm(
  seedInput: string,
  iterationsInput: string,
): FormParseResult<BenchmarkRequest> {
  if (seedInput.trim() === "") return { ok: false, issue: SEED_ISSUE }
  if (iterationsInput.trim() === "") return { ok: false, issue: ITERATION_ISSUE }
  const parsed = BenchmarkRequestSchema.safeParse({
    seed: Number(seedInput),
    iterations: Number(iterationsInput),
  })
  if (parsed.success) return { ok: true, value: parsed.data }
  const iterationFailed = parsed.error.issues.some((issue) => issue.path[0] === "iterations")
  return { ok: false, issue: iterationFailed ? ITERATION_ISSUE : SEED_ISSUE }
}
