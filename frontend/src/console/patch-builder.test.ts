import { describe, expect, it } from "vitest"
import { ScenarioResponseSchema } from "../contracts/generated"
import { HASHES, scenario } from "../state/workflow-fixtures"
import { buildTypedPatch, defaultPatchInput } from "./patch-builder"

describe("typed patch builder", () => {
  it("maps the scenario fault family to a compatible typed operation", () => {
    const backhaul = ScenarioResponseSchema.parse({
      ...scenario,
      scenario: {
        ...scenario.scenario,
        scenario_id: "scenario-backhaul-001",
        fault_family: "backhaul-degradation",
        target_ids: ["backhaul-001"],
      },
      topology_hash: HASHES.topology,
    })

    const input = defaultPatchInput(backhaul)

    expect(input.targetKind).toBe("backhaul")
    expect(input.operation).toBe("restore-backhaul-capacity")
  })

  it("returns the exact scalar parameter object after contract parsing", () => {
    const input = {
      ...defaultPatchInput(scenario),
      parametersJson: '{"capacity_ues":230,"safe":true}',
    }

    const result = buildTypedPatch(scenario, input)

    expect(result.ok).toBe(true)
    if (result.ok)
      expect(result.patch.changes[0]?.parameters).toEqual({ capacity_ues: 230, safe: true })
  })
})
