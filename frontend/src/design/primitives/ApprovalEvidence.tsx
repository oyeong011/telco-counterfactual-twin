import { ClipboardCheck, ShieldCheck, ShieldX } from "lucide-react"
import { useId } from "react"
import { ErrorState } from "./ErrorState"
import { SURFACE_TONES, type SurfaceState } from "./primitiveTypes"
import { Skeleton } from "./Skeleton"
import { StatusChip, type StatusTone } from "./StatusChip"

export type ApprovalStep = {
  readonly id: string
  readonly label: string
  readonly state: "pending" | "complete" | "rejected"
}

export type ApprovalDecision = "pending" | "approved" | "rejected"
export type ApprovalAction = "approve" | "reject"

type ApprovalEvidenceProps = {
  readonly state: SurfaceState
  readonly decision?: ApprovalDecision
  readonly highlightedAction?: ApprovalAction
  readonly steps: readonly ApprovalStep[]
  readonly reason?: string
  readonly proofHash?: string
  readonly actionsDisabledReason?: string
  readonly onApprove?: () => void
  readonly onReject?: () => void
  readonly onHighlightAction?: (action: ApprovalAction | undefined) => void
  readonly onRetry?: () => void
}

function decisionFor(
  state: SurfaceState,
  decision: ApprovalDecision | undefined,
): ApprovalDecision {
  if (decision !== undefined) return decision
  if (state === "approved") return "approved"
  if (state === "rejected") return "rejected"
  return "pending"
}

export function ApprovalEvidence({
  state,
  decision,
  highlightedAction,
  steps,
  reason,
  proofHash,
  actionsDisabledReason,
  onApprove,
  onReject,
  onHighlightAction,
  onRetry,
}: ApprovalEvidenceProps) {
  const headingId = useId()
  const resolvedDecision = decisionFor(state, decision)

  if (state === "loading") {
    return <Skeleton variant="evidence" label="Loading approval evidence" />
  }
  if (state === "error") {
    return (
      <ErrorState
        title="Approval evidence unavailable"
        code="APPROVAL_UNAVAILABLE"
        detail="The evidence-only decision record could not be loaded."
        {...(onRetry ? { onRetry } : {})}
      />
    )
  }
  const tone: StatusTone = SURFACE_TONES[state]

  return (
    <section className="panel approvalEvidence" data-state={state} aria-labelledby={headingId}>
      <div className="panelHeader">
        <h2 id={headingId}>
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
        <div className="approvalActions" data-decision={resolvedDecision}>
          {onApprove ? (
            <button
              type="button"
              aria-pressed={resolvedDecision === "approved"}
              data-highlighted={highlightedAction === "approve" || undefined}
              disabled={Boolean(actionsDisabledReason)}
              title={actionsDisabledReason}
              onClick={onApprove}
              onPointerEnter={() => onHighlightAction?.("approve")}
              onPointerLeave={() => onHighlightAction?.(undefined)}
              onFocus={() => onHighlightAction?.("approve")}
              onBlur={() => onHighlightAction?.(undefined)}
            >
              <ShieldCheck aria-hidden="true" />
              Record approval evidence
            </button>
          ) : null}
          {onReject ? (
            <button
              type="button"
              aria-pressed={resolvedDecision === "rejected"}
              data-highlighted={highlightedAction === "reject" || undefined}
              onClick={onReject}
              onPointerEnter={() => onHighlightAction?.("reject")}
              onPointerLeave={() => onHighlightAction?.(undefined)}
              onFocus={() => onHighlightAction?.("reject")}
              onBlur={() => onHighlightAction?.(undefined)}
            >
              <ShieldX aria-hidden="true" />
              Record rejection evidence
            </button>
          ) : null}
        </div>
      ) : null}
      <p className="approvalBoundary">Approval records evidence only. It never executes a patch.</p>
    </section>
  )
}
