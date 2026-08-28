import { describe, expect, it, vi } from "vitest"
import { EvidenceResponseSchema } from "../contracts/generated"
import { HASHES, scenario, session } from "../state/workflow-fixtures"
import { downloadEvidenceJsonWithPort, type EvidenceDownloadPort } from "./evidence-download"

const evidence = EvidenceResponseSchema.parse({
  run_id: scenario.run_id,
  evidence_card: {
    schema_version: "1.0",
    evidence_id: "evidence-download-001",
    session_id: session.session_id,
    scenario_hash: HASHES.scenario,
    patch_hash: HASHES.patch,
    simulation_hash: HASHES.simulation,
    policy_hash: HASHES.policy,
    approval_proof_hash: null,
    seed: scenario.scenario.seed,
    source_commit_sha: "b".repeat(40),
    contract_hashes: { scenario: HASHES.scenario },
    generated_at: "2026-08-28T00:00:06Z",
  },
  events: [],
  approval_proof: null,
})

describe("evidence JSON download", () => {
  it("clicks an attached named file and revokes its object URL after deferral", async () => {
    const clicks: Array<{ attached: boolean; download: string }> = []
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      clicks.push({ attached: document.body.contains(this), download: this.download })
    })
    const blobs: Blob[] = []
    const deferredTasks: Array<() => void> = []
    const revoke = vi.fn()
    const port: EvidenceDownloadPort = {
      document,
      createObjectUrl: (blob) => {
        blobs.push(blob)
        return "blob:evidence-download"
      },
      revokeObjectUrl: revoke,
      defer: (task) => {
        deferredTasks.push(task)
      },
    }

    downloadEvidenceJsonWithPort(evidence, port)

    expect(clicks).toEqual([{ attached: true, download: "evidence-download-001.json" }])
    expect(document.querySelector('a[download="evidence-download-001.json"]')).toBeNull()
    expect(revoke).not.toHaveBeenCalled()
    const blob = blobs[0]
    if (blob === undefined) throw new TypeError("download blob was not created")
    expect(await blob.text()).toContain('"evidence_id": "evidence-download-001"')
    const deferred = deferredTasks[0]
    if (deferred === undefined) throw new TypeError("URL revocation was not deferred")
    deferred()
    expect(revoke).toHaveBeenCalledWith("blob:evidence-download")
    click.mockRestore()
  })
})
