import { ApprovalEvidence } from "../design/primitives/ApprovalEvidence"
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

function EvidenceExample({ state }: { readonly state: ShowcaseState }) {
  return (
    <EvidenceRail
      title="Evidence package"
      fields={EVIDENCE_FIELDS}
      state={surfaceStateFor(state)}
    />
  )
}

function ApprovalExample({ state }: { readonly state: ShowcaseState }) {
  const surfaceState = surfaceStateFor(state)
  const reason = surfaceState === "rejected" ? "Freshness policy blocked this record." : undefined
  const proofHash = surfaceState === "approved" ? KOREAN_HASH : undefined
  return (
    <ApprovalEvidence
      state={surfaceState}
      steps={APPROVAL_STEPS}
      {...(reason ? { reason } : {})}
      {...(proofHash ? { proofHash } : {})}
    />
  )
}

function ErrorExample({ state }: { readonly state: ShowcaseState }) {
  return (
    <ErrorState
      title={`${stateTone(state)} recovery state`}
      code={`SHOWCASE_${state.toUpperCase()}`}
      detail="Recovery remains evidence-only and does not execute a patch."
      requestId="fixture-request-92"
      blocking={state === "error" || state === "rejected"}
      retryDisabled={state === "disabled"}
      onRetry={() => undefined}
    />
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
