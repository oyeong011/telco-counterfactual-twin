import { describe, expect, it } from "vitest"
import { type FaultFamily, ScenarioResponseSchema } from "../contracts/generated"
import { HASHES, scenario } from "../state/workflow-fixtures"
import { buildTypedPatch, defaultPatchInput } from "./patch-builder"

describe("typed patch builder", () => {
  const scenarioFor = (faultFamily: FaultFamily, targetId: string) =>
    ScenarioResponseSchema.parse({
      ...scenario,
      scenario: {
        ...scenario.scenario,
        scenario_id: `scenario-${faultFamily}`,
        fault_family: faultFamily,
        target_ids: [targetId],
      },
      topology_hash: HASHES.topology,
    })

  it.each([
    ["radio-congestion", "cell-0001", "cell", "adjust-radio-capacity", { capacity_ues: 230 }],
    [
      "backhaul-degradation",
      "backhaul-0001",
      "backhaul",
      "restore-backhaul-capacity",
      { capacity_mbps: 8000 },
    ],
    ["upf-saturation", "upf-0001", "upf", "scale-upf-capacity", { capacity_units: 160 }],
    [
      "neighbor-handover-misconfiguration",
      "cell-0001",
      "neighbor-relation",
      "correct-neighbor-relation",
      { relation_valid: true },
    ],
    [
      "slice-scheduler-misallocation",
      "slice-embb",
      "slice",
      "rebalance-slice-weight",
      { scheduler_weight: 60 },
    ],
    [
      "alarm-prompt-injection",
      "cell-0001",
      "alarm",
      "ignore-untrusted-alarm",
      { alarm_ignored: true },
    ],
  ] as const)(
    "maps %s to one backend-valid operation contract",
    (faultFamily, targetId, targetKind, operation, parameters) => {
      const input = defaultPatchInput(scenarioFor(faultFamily, targetId))

      expect(input.targetKind).toBe(targetKind)
      expect(input.operation).toBe(operation)
      expect(JSON.parse(input.parametersJson)).toEqual(parameters)
    },
  )

  it("returns the exact scalar parameter object after contract parsing", () => {
    const input = {
      ...defaultPatchInput(scenario),
      parametersJson: '{"capacity_ues":230}',
    }

    const result = buildTypedPatch(scenario, input)

    expect(result.ok).toBe(true)
    if (result.ok) expect(result.patch.changes[0]?.parameters).toEqual({ capacity_ues: 230 })
  })

  it("rejects unsupported keys before sending the patch", () => {
    const input = {
      ...defaultPatchInput(scenario),
      parametersJson: '{"capacity_ues":230,"safe":true}',
    }

    const result = buildTypedPatch(scenario, input)

    expect(result).toEqual({
      ok: false,
      issue: 'adjust-radio-capacity requires exactly the parameter "capacity_ues".',
    })
  })

  it("rejects a semantically invalid operation value before sending the patch", () => {
    const input = { ...defaultPatchInput(scenario), parametersJson: '{"capacity_ues":1001}' }

    const result = buildTypedPatch(scenario, input)

    expect(result).toEqual({
      ok: false,
      issue: "capacity_ues must be an integer between 1 and 1000.",
    })
  })
})
