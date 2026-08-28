import { ClipboardCheck, ShieldCheck, ShieldX } from "lucide-react"
import { ErrorState } from "./ErrorState"
import { SURFACE_TONES, type SurfaceState } from "./primitiveTypes"
import { Skeleton } from "./Skeleton"
import { StatusChip, type StatusTone } from "./StatusChip"

export type ApprovalStep = {
  readonly id: string
  readonly label: string
  readonly state: "pending" | "complete" | "rejected"
}

type ApprovalEvidenceProps = {
  readonly state: SurfaceState
  readonly steps: readonly ApprovalStep[]
  readonly reason?: string
  readonly proofHash?: string
  readonly actionsDisabledReason?: string
  readonly onApprove?: () => void
  readonly onReject?: () => void
}

export function ApprovalEvidence({
  state,
  steps,
  reason,
  proofHash,
  actionsDisabledReason,
  onApprove,
  onReject,
}: ApprovalEvidenceProps) {
  if (state === "loading") {
    return <Skeleton variant="evidence" label="Loading approval evidence" />
  }
  if (state === "error") {
    return (
      <ErrorState
        title="Approval evidence unavailable"
        code="APPROVAL_UNAVAILABLE"
        detail="The evidence-only decision record could not be loaded."
      />
    )
  }
  const tone: StatusTone = SURFACE_TONES[state]

  return (
    <section className="panel approvalEvidence" aria-labelledby="approval-title">
      <div className="panelHeader">
        <h2 id="approval-title">
          <ClipboardCheck aria-hidden="true" />
          Approval evidence
        </h2>
        <StatusChip tone={tone} label={state} />
      </div>
      {state === "empty" ? (
        <p className="emptyMessage">No approval was requested.</p>
      ) : (
        <ol className="approvalSteps" aria-label="Approval review steps">
          {steps.map((step) => (
            <li key={step.id} data-state={step.state}>
              <span>{step.label}</span>
              <StatusChip
                tone={step.state === "rejected" ? "rejected" : "neutral"}
                label={step.state}
              />
            </li>
          ))}
        </ol>
      )}
      {reason ? <p className="approvalReason">Reason: {reason}</p> : null}
      {proofHash ? <p className="mono">Proof {proofHash}</p> : null}
      {onApprove || onReject ? (
        <div className="approvalActions">
          <button
            type="button"
            disabled={Boolean(actionsDisabledReason)}
            title={actionsDisabledReason}
            onClick={onApprove}
          >
            <ShieldCheck aria-hidden="true" />
            Record approval evidence
          </button>
          <button type="button" onClick={onReject}>
            <ShieldX aria-hidden="true" />
            Record rejection evidence
          </button>
        </div>
      ) : null}
      <p className="approvalBoundary">Approval records evidence only. It never executes a patch.</p>
    </section>
  )
}
