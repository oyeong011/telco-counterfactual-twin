import { useState } from "react"
import { ApprovalEvidence, type ApprovalStep } from "../design/primitives/ApprovalEvidence"
import { ErrorState } from "../design/primitives/ErrorState"
import { EvidenceRail } from "../design/primitives/EvidenceRail"
import { SKELETON_VARIANTS } from "../design/primitives/primitiveTypes"
import { Skeleton } from "../design/primitives/Skeleton"
import { StatusChip } from "../design/primitives/StatusChip"
import { type ShowcaseState, surfaceStateFor } from "./primitiveStateRegistry"
import { ShowcaseStateSection } from "./ShowcaseStates"
import { APPROVAL_STEPS, EVIDENCE_FIELDS } from "./showcaseFixtures"
import { stateTone } from "./showcaseStateTone"

const KOREAN_COPY = "승인은 증거만 기록하며 네트워크를 실행하지 않습니다."
const KOREAN_HASH = "sha256:한글-증거-해시-0123456789abcdef0123456789abcdef"

function pendingSteps(): readonly ApprovalStep[] {
  return APPROVAL_STEPS.map((step) => ({ ...step, state: "pending" }))
}

function approvedSteps(): readonly ApprovalStep[] {
  return APPROVAL_STEPS.map((step) => ({ ...step, state: "complete" }))
}

function EvidenceExample({ state }: { readonly state: ShowcaseState }) {
  const [copied, setCopied] = useState(false)
  const [retried, setRetried] = useState(false)
  return (
    <div className="showcaseEvidenceExample" data-behavior-state={state}>
      <EvidenceRail
        title="Evidence package"
        fields={state === "empty" ? [] : EVIDENCE_FIELDS}
        state={surfaceStateFor(state)}
        copyDisabled={state === "disabled"}
        onCopy={() => setCopied(true)}
        onRetry={() => setRetried(true)}
      />
      {copied ? <span role="status">Evidence hash copied.</span> : null}
      {retried ? <span role="status">Evidence retry requested.</span> : null}
    </div>
  )
}

function ApprovalExample({ state }: { readonly state: ShowcaseState }) {
  const [decision, setDecision] = useState<"pending" | "approved" | "rejected">("pending")
  const [recovered, setRecovered] = useState(false)
  const baseState = surfaceStateFor(state)
  const effectiveState =
    state === "error" && recovered ? "default" : decision === "pending" ? baseState : decision
  const actionsDisabledReason =
    state === "disabled"
      ? "Approval controls are disabled for this fixture."
      : state === "stale"
        ? "Freshness policy blocked this record."
        : state === "demo"
          ? "Synthetic demo evidence cannot be approved."
          : state === "approved"
            ? "Approval evidence is already recorded."
            : undefined
  const reason =
    effectiveState === "rejected"
      ? "Freshness policy blocked this record."
      : effectiveState === "stale"
        ? "The observation is outside the approval freshness window."
        : undefined
  const steps =
    effectiveState === "approved"
      ? approvedSteps()
      : effectiveState === "rejected"
        ? APPROVAL_STEPS
        : pendingSteps()
  return (
    <div className="showcaseApprovalExample" data-behavior-state={state}>
      <ApprovalEvidence
        state={effectiveState}
        steps={steps}
        {...(reason ? { reason } : {})}
        {...(effectiveState === "approved" ? { proofHash: KOREAN_HASH } : {})}
        {...(actionsDisabledReason ? { actionsDisabledReason } : {})}
        onApprove={() => setDecision("approved")}
        {...(state === "approved" ? {} : { onReject: () => setDecision("rejected") })}
        onRetry={() => setRecovered(true)}
      />
      {decision !== "pending" ? <span role="status">Decision recorded: {decision}.</span> : null}
    </div>
  )
}

function ErrorExample({ state }: { readonly state: ShowcaseState }) {
  const [retryRequested, setRetryRequested] = useState(false)
  return (
    <div className="showcaseErrorExample" data-behavior-state={state}>
      <ErrorState
        title={`${stateTone(state)} recovery state`}
        code={`SHOWCASE_${state.toUpperCase()}`}
        detail={
          state === "stale"
            ? "The observation is too old; refresh evidence before retrying."
            : state === "rejected"
              ? "The policy rejected this evidence; inspect the recorded reason."
              : "Recovery remains evidence-only and does not execute a patch."
        }
        requestId="fixture-request-92"
        blocking={state === "error" || state === "rejected"}
        retryDisabled={state === "disabled" || state === "loading"}
        onRetry={() => setRetryRequested(true)}
      />
      {retryRequested ? <span role="status">Retry requested.</span> : null}
    </div>
  )
}

function SkeletonExample() {
  return (
    <div className="showcaseSkeletonSet">
      {SKELETON_VARIANTS.map((variant) => (
        <Skeleton key={variant} variant={variant} label={`Loading ${variant}`} rows={2} />
      ))}
    </div>
  )
}

export function ShowcaseEvidence() {
  return (
    <div className="showcaseStack">
      <ShowcaseStateSection
        primitive="EvidenceRail"
        description="Evidence details are visible on desktop and open as a focus-managed mobile sheet."
      >
        {(state) => <EvidenceExample state={state} />}
      </ShowcaseStateSection>
      <ShowcaseStateSection
        primitive="ApprovalEvidence"
        description="Reviewer steps and proof metadata record a decision without granting execution authority."
      >
        {(state) => <ApprovalExample state={state} />}
      </ShowcaseStateSection>
      <ShowcaseStateSection
        primitive="ErrorState"
        description="Failure copy names the code, request, and safe recovery action without relying on color."
      >
        {(state) => <ErrorExample state={state} />}
      </ShowcaseStateSection>
      <ShowcaseStateSection
        primitive="Skeleton"
        description="Loading reserves final geometry; reduced motion keeps the placeholder static."
      >
        {() => <SkeletonExample />}
      </ShowcaseStateSection>
      <section className="showcaseCjkEvidence" aria-label="CJK evidence sample">
        <div>
          <StatusChip tone="info" label="CJK wrapping sample" />
          <h2>한국어 증거 경계</h2>
        </div>
        <p>{KOREAN_COPY}</p>
        <code className="mono">{KOREAN_HASH}</code>
      </section>
    </div>
  )
}
