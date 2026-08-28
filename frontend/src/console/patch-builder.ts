import {
  type FaultFamily,
  type PatchOperation,
  PatchOperationSchema,
  SafePropertiesSchema,
  type ScenarioResponse,
  type TargetKind,
  TargetKindSchema,
  type TypedPatch,
  TypedPatchSchema,
  UtcTimestampSchema,
} from "../contracts/generated"

const PATCH_BY_FAULT = {
  "radio-congestion": { targetKind: "cell", operation: "adjust-radio-capacity" },
  "backhaul-degradation": {
    targetKind: "backhaul",
    operation: "restore-backhaul-capacity",
  },
  "upf-saturation": { targetKind: "upf", operation: "scale-upf-capacity" },
  "neighbor-handover-misconfiguration": {
    targetKind: "neighbor-relation",
    operation: "correct-neighbor-relation",
  },
  "slice-scheduler-misallocation": {
    targetKind: "slice",
    operation: "rebalance-slice-weight",
  },
  "alarm-prompt-injection": { targetKind: "alarm", operation: "ignore-untrusted-alarm" },
} as const satisfies Record<
  FaultFamily,
  { readonly targetKind: TargetKind; readonly operation: PatchOperation }
>

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

export function defaultPatchInput(scenario: ScenarioResponse): PatchEditorInput {
  const targetId = scenario.scenario.target_ids[0]
  const template = PATCH_BY_FAULT[scenario.scenario.fault_family]
  return {
    patchId: `patch-${globalThis.crypto.randomUUID()}`,
    targetId: targetId ?? "target-required",
    targetKind: template.targetKind,
    operation: template.operation,
    parametersJson: "{}",
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
  const patch = TypedPatchSchema.safeParse({
    schema_version: "1.0",
    patch_id: input.patchId,
    scenario_id: scenario.scenario.scenario_id,
    base_topology_hash: scenario.topology_hash,
    changes: [
      {
        target_id: input.targetId,
        target_kind: TargetKindSchema.parse(input.targetKind),
        operation: PatchOperationSchema.parse(input.operation),
        parameters: parameters.data,
      },
    ],
    blast_radius: {
      max_cells: input.maxCells,
      max_ue_cohorts: input.maxUeCohorts,
      max_slices: input.maxSlices,
    },
    proposed_at: UtcTimestampSchema.parse(input.proposedAt),
  })
  if (!patch.success) return { ok: false, issue: "Patch fields do not satisfy the typed contract." }
  return { ok: true, patch: patch.data }
}
