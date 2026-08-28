import { useState } from "react"
import { useConsole } from "../console/ConsoleContext"
import { ContextRail, type ContextRailItem } from "../design/primitives/ContextRail"
import { type EvidenceField, EvidenceRail } from "../design/primitives/EvidenceRail"

export function ScenarioRail() {
  const { model } = useConsole()
  const selectedId = model.snapshot.scenario?.scenario.scenario_id
  const items = model.scenarios.map(
    (item): ContextRailItem => ({
      id: item.scenario.scenario_id,
      label: item.scenario.fault_family,
      metadata: String(item.scenario.seed),
      tone: item.scenario.scenario_id === selectedId ? "info" : "neutral",
      disabled: item.scenario.scenario_id !== selectedId,
      ...(item.scenario.scenario_id === selectedId
        ? {}
        : {
            disabledReason:
              "The HTTP API has no recoverable run aggregate for switching active drafts.",
          }),
    }),
  )
  return (
    <ContextRail
      title="Session scenarios"
      items={items}
      {...(selectedId ? { selectedId } : {})}
      state={model.busy === "scenario" ? "loading" : items.length === 0 ? "empty" : "default"}
    />
  )
}

function evidenceFields(model: ReturnType<typeof useConsole>["model"]): readonly EvidenceField[] {
  const card = model.snapshot.evidence?.evidence_card
  const proof = model.snapshot.evidence?.approval_proof
  if (card !== undefined)
    return [
      { id: "evidence", label: "Evidence ID", value: card.evidence_id },
      { id: "scenario", label: "Scenario hash", value: card.scenario_hash },
      { id: "patch", label: "Patch hash", value: card.patch_hash },
      { id: "simulation", label: "Simulation hash", value: card.simulation_hash },
      { id: "policy", label: "Policy hash", value: card.policy_hash },
      {
        id: "proof",
        label: "Approval proof content hash",
        value: card.approval_proof_hash ?? "Pending",
      },
      ...(proof
        ? [
            { id: "proof-id", label: "Proof ID", value: proof.proof_id },
            { id: "certificate", label: "Certificate hash", value: proof.certificate_hash },
            {
              id: "proof-signature",
              label: "Proof signature (browser verification not performed)",
              value: proof.proof_signature,
            },
          ]
        : []),
    ]
  const comparison = model.snapshot.comparison?.comparison.evidence_hashes
  if (comparison !== undefined)
    return [
      { id: "patch", label: "Patch hash", value: comparison.patch_hash },
      { id: "baseline", label: "Baseline trace", value: comparison.baseline_trace_hash },
      { id: "candidate", label: "Candidate trace", value: comparison.candidate_trace_hash },
      { id: "constraints", label: "Constraint set", value: comparison.constraint_set_hash },
    ]
  if (model.snapshot.scenario !== undefined)
    return [
      {
        id: "topology",
        label: "Topology hash",
        value: model.snapshot.scenario.topology_hash,
      },
      {
        id: "scenario",
        label: "Scenario hash",
        value: model.snapshot.scenario.scenario_hash,
      },
    ]
  return []
}

export function CurrentEvidenceRail() {
  const { model } = useConsole()
  const [selectedArtifactId, setSelectedArtifactId] = useState<string>()
  const fields = evidenceFields(model)
  const evidenceHash = model.snapshot.evidence?.evidence_card.approval_proof_hash
  const state = model.snapshot.evidence
    ? model.snapshot.decision?.state === "approved"
      ? "approved"
      : "rejected"
    : fields.length === 0
      ? "empty"
      : "default"
  return (
    <EvidenceRail
      title="Evidence ledger"
      state={state}
      fields={fields}
      {...(selectedArtifactId ? { selectedArtifactId } : {})}
      onSelectArtifact={setSelectedArtifactId}
      {...(evidenceHash
        ? {
            onCopy: () => void navigator.clipboard.writeText(evidenceHash),
          }
        : {})}
    />
  )
}
