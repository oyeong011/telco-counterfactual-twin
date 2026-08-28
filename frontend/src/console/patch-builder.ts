import {
  type FaultFamily,
  type JsonScalar,
  type PatchOperation,
  SafePropertiesSchema,
  type ScenarioResponse,
  type TargetKind,
  type TypedPatch,
  TypedPatchSchema,
} from "../contracts/generated"

type OperationSpec = {
  readonly targetKind: TargetKind
  readonly parameterName: string
  readonly defaultValue: JsonScalar
  readonly validate: (value: JsonScalar) => string | null
}

const integerRange = (name: string, minimum: number, maximum: number) => (value: JsonScalar) =>
  typeof value === "number" && Number.isInteger(value) && value >= minimum && value <= maximum
    ? null
    : `${name} must be an integer between ${minimum} and ${maximum}.`

const numberRange = (name: string, minimum: number, maximum: number) => (value: JsonScalar) =>
  typeof value === "number" && Number.isFinite(value) && value >= minimum && value <= maximum
    ? null
    : `${name} must be a number between ${minimum} and ${maximum}.`

const requiredTrue = (name: string) => (value: JsonScalar) =>
  value === true ? null : `${name} must be true.`

const OPERATION_SPECS = {
  "adjust-radio-capacity": {
    targetKind: "cell",
    parameterName: "capacity_ues",
    defaultValue: 230,
    validate: integerRange("capacity_ues", 1, 1000),
  },
  "restore-backhaul-capacity": {
    targetKind: "backhaul",
    parameterName: "capacity_mbps",
    defaultValue: 8000,
    validate: numberRange("capacity_mbps", 1, 1_000_000),
  },
  "scale-upf-capacity": {
    targetKind: "upf",
    parameterName: "capacity_units",
    defaultValue: 160,
    validate: integerRange("capacity_units", 1, 10_000),
  },
  "correct-neighbor-relation": {
    targetKind: "neighbor-relation",
    parameterName: "relation_valid",
    defaultValue: true,
    validate: requiredTrue("relation_valid"),
  },
  "rebalance-slice-weight": {
    targetKind: "slice",
    parameterName: "scheduler_weight",
    defaultValue: 60,
    validate: integerRange("scheduler_weight", 1, 100),
  },
  "ignore-untrusted-alarm": {
    targetKind: "alarm",
    parameterName: "alarm_ignored",
    defaultValue: true,
    validate: requiredTrue("alarm_ignored"),
  },
} as const satisfies Record<PatchOperation, OperationSpec>

const PATCH_BY_FAULT = {
  "radio-congestion": "adjust-radio-capacity",
  "backhaul-degradation": "restore-backhaul-capacity",
  "upf-saturation": "scale-upf-capacity",
  "neighbor-handover-misconfiguration": "correct-neighbor-relation",
  "slice-scheduler-misallocation": "rebalance-slice-weight",
  "alarm-prompt-injection": "ignore-untrusted-alarm",
} as const satisfies Record<FaultFamily, PatchOperation>

export type PatchEditorInput = {
  readonly patchId: string
  readonly targetId: string
  readonly targetKind: TargetKind
  readonly operation: PatchOperation
  readonly parametersJson: string
  readonly maxCells: number
  readonly maxUeCohorts: number
  readonly maxSlices: number
  readonly proposedAt: string
}

export type PatchBuildResult =
  | { readonly ok: true; readonly patch: TypedPatch }
  | { readonly ok: false; readonly issue: string }

export function utcTimestampNow(): string {
  return new Date().toISOString().replace(/\.\d{3}Z$/, "Z")
}

export function patchDefaultsForOperation(operation: PatchOperation): {
  readonly targetKind: TargetKind
  readonly parametersJson: string
} {
  const spec = OPERATION_SPECS[operation]
  return {
    targetKind: spec.targetKind,
    parametersJson: JSON.stringify({ [spec.parameterName]: spec.defaultValue }, null, 2),
  }
}

export function defaultPatchInput(scenario: ScenarioResponse): PatchEditorInput {
  const targetId = scenario.scenario.target_ids[0]
  const operation = PATCH_BY_FAULT[scenario.scenario.fault_family]
  const defaults = patchDefaultsForOperation(operation)
  return {
    patchId: `patch-${globalThis.crypto.randomUUID()}`,
    targetId: targetId ?? "target-required",
    targetKind: defaults.targetKind,
    operation,
    parametersJson: defaults.parametersJson,
    maxCells: 1,
    maxUeCohorts: 1,
    maxSlices: 1,
    proposedAt: utcTimestampNow(),
  }
}

export function buildTypedPatch(
  scenario: ScenarioResponse,
  input: PatchEditorInput,
): PatchBuildResult {
  let rawParameters: unknown
  try {
    rawParameters = JSON.parse(input.parametersJson)
  } catch (error) {
    if (error instanceof SyntaxError) return { ok: false, issue: "Parameters must be valid JSON." }
    throw error
  }
  const parameters = SafePropertiesSchema.safeParse(rawParameters)
  if (!parameters.success)
    return { ok: false, issue: "Parameters must be a bounded object with safe scalar values." }
  const spec = OPERATION_SPECS[input.operation]
  if (input.targetKind !== spec.targetKind)
    return {
      ok: false,
      issue: `${input.operation} requires target kind "${spec.targetKind}".`,
    }
  const keys = Object.keys(parameters.data)
  if (keys.length !== 1 || keys[0] !== spec.parameterName)
    return {
      ok: false,
      issue: `${input.operation} requires exactly the parameter "${spec.parameterName}".`,
    }
  const parameter = Object.entries(parameters.data).find(([key]) => key === spec.parameterName)
  if (parameter === undefined)
    return {
      ok: false,
      issue: `${input.operation} requires exactly the parameter "${spec.parameterName}".`,
    }
  const semanticIssue = spec.validate(parameter[1])
  if (semanticIssue !== null) return { ok: false, issue: semanticIssue }
  const patch = TypedPatchSchema.safeParse({
    schema_version: "1.0",
    patch_id: input.patchId,
    scenario_id: scenario.scenario.scenario_id,
    base_topology_hash: scenario.topology_hash,
    changes: [
      {
        target_id: input.targetId,
        target_kind: input.targetKind,
        operation: input.operation,
        parameters: parameters.data,
      },
    ],
    blast_radius: {
      max_cells: input.maxCells,
      max_ue_cohorts: input.maxUeCohorts,
      max_slices: input.maxSlices,
    },
    proposed_at: input.proposedAt,
  })
  if (!patch.success) return { ok: false, issue: "Patch fields do not satisfy the typed contract." }
  return { ok: true, patch: patch.data }
}
