import { ApprovalEvidence } from "../design/primitives/ApprovalEvidence"
import { ErrorState } from "../design/primitives/ErrorState"
import { EvidenceRail } from "../design/primitives/EvidenceRail"
import { APPROVAL_STEPS, EVIDENCE_FIELDS } from "./showcaseFixtures"

export function ShowcaseEvidence() {
  return (
    <section className="showcaseStack" id="evidence" aria-labelledby="evidence-heading">
      <div className="showcaseSectionHeading">
        <h2 id="evidence-heading">Evidence and decision states</h2>
        <p>Approval is recorded as evidence and never presented as execution authority.</p>
      </div>
      <div className="showcaseGrid">
        <EvidenceRail title="Signed evidence package" state="approved" fields={EVIDENCE_FIELDS} />
        <ApprovalEvidence
          state="rejected"
          steps={APPROVAL_STEPS}
          reason="Observation freshness exceeded the policy threshold"
        />
        <ApprovalEvidence
          state="approved"
          steps={[
            { id: "engineer", label: "Engineer review", state: "complete" },
            { id: "policy", label: "Policy constraint review", state: "complete" },
          ]}
          proofHash="sha256:fixture-evidence-7f3f"
        />
        <ErrorState
          title="Evidence package unavailable"
          code="EVIDENCE_TIMEOUT"
          detail="The sample package could not be opened. Retry is safe because it only reloads evidence."
          requestId="fixture-request-91"
          blocking
          onRetry={() => undefined}
        />
      </div>
    </section>
  )
}
