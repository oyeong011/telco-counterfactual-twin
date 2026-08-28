import { Activity, Network } from "lucide-react"
import { useState } from "react"
import { type AppNavigationItem, AppShell } from "../design/primitives/AppShell"
import { CommandBar } from "../design/primitives/CommandBar"
import { ContextRail } from "../design/primitives/ContextRail"
import { ErrorState } from "../design/primitives/ErrorState"
import { Skeleton } from "../design/primitives/Skeleton"
import { StatusChip } from "../design/primitives/StatusChip"
import { type ShowcaseState, surfaceStateFor } from "./primitiveStateRegistry"
import { ShowcaseStateSection } from "./ShowcaseStates"
import { CONTEXT_ITEMS } from "./showcaseFixtures"
import { stateTone } from "./showcaseStateTone"

const PREVIEW_NAVIGATION = [
  { label: "Workbench", href: "#preview-workbench", icon: Network, active: true },
  { label: "Activity", href: "#preview-activity", icon: Activity, active: false },
] as const satisfies readonly AppNavigationItem[]

function navigationForState(state: ShowcaseState): readonly AppNavigationItem[] {
  if (state === "active") {
    return PREVIEW_NAVIGATION.map((item, index) => ({ ...item, active: index === 1 }))
  }
  if (state === "disabled") {
    return PREVIEW_NAVIGATION.map((item) => ({
      ...item,
      disabled: true,
      active: false,
    }))
  }
  if (state === "focus") {
    return PREVIEW_NAVIGATION.map((item, index) => ({ ...item, focus: index === 0 }))
  }
  return PREVIEW_NAVIGATION
}

function shellBody(state: ShowcaseState) {
  switch (state) {
    case "loading":
      return <Skeleton variant="table" label="Loading shell route" rows={3} />
    case "empty":
      return <p className="emptyMessage">No route data selected.</p>
    case "disabled":
      return <p className="showcasePreviewCopy">Route controls are disabled for this fixture.</p>
    case "error":
      return (
        <ErrorState
          title="Shell route unavailable"
          code="SHELL_ROUTE_UNAVAILABLE"
          detail="The route state could not be read. Retry the evidence request."
          blocking
          onRetry={() => undefined}
        />
      )
    case "stale":
    case "rejected":
    case "approved":
    case "demo":
      return (
        <div className="showcasePreviewState" data-state={state}>
          <StatusChip tone={stateTone(state)} label={state} metadata="route status" />
          <p className="showcasePreviewCopy">
            {state === "demo"
              ? "Synthetic route data is clearly bounded to the showcase."
              : `Route evidence is ${state} and remains visible for review.`}
          </p>
        </div>
      )
    case "default":
    case "hover":
    case "active":
    case "focus":
      return <p className="showcasePreviewCopy">Bounded route body · {state} chrome</p>
    default: {
      const exhaustiveState: never = state
      throw new TypeError(`Unsupported AppShell state: ${String(exhaustiveState)}`)
    }
  }
}

function AppShellExample({ state }: { readonly state: ShowcaseState }) {
  return (
    <AppShell
      preview
      previewLabel={`AppShell ${state} preview navigation`}
      navigation={navigationForState(state)}
      commandBar={
        <CommandBar
          title="Shell preview"
          status={{ tone: stateTone(state), label: state }}
          announcement={`AppShell ${state} state`}
        />
      }
    >
      {shellBody(state)}
    </AppShell>
  )
}

function CommandBarExample({ state }: { readonly state: ShowcaseState }) {
  const [reviewRecorded, setReviewRecorded] = useState(false)
  const isUnavailable = state === "disabled" || state === "loading"
  const actionLabel = state === "loading" ? "Checking evidence" : "Review evidence"
  return (
    <>
      <CommandBar
        title="Route command"
        status={{ tone: stateTone(state), label: state, metadata: "fixture" }}
        announcement={`Command bar ${state} state`}
        actions={
          <button
            type="button"
            aria-pressed={state === "active" || reviewRecorded}
            data-showcase-focus={state === "focus" ? "true" : undefined}
            disabled={isUnavailable}
            onClick={() => setReviewRecorded(true)}
          >
            {reviewRecorded ? "Review recorded" : actionLabel}
          </button>
        }
      />
      {state === "empty" ? <p className="emptyMessage">No route action is available.</p> : null}
      {state === "error" ? (
        <ErrorState
          title="Command unavailable"
          code="COMMAND_UNAVAILABLE"
          detail="Retry the evidence request; recovery remains evidence-only."
          onRetry={() => setReviewRecorded(true)}
        />
      ) : null}
      {state === "approved" ? (
        <p className="showcasePreviewCopy">Approval proof is attached to this command.</p>
      ) : null}
      {state === "rejected" ? (
        <p className="showcasePreviewCopy">
          Rejected evidence keeps the safe review action visible.
        </p>
      ) : null}
    </>
  )
}

function ContextRailExample({ state }: { readonly state: ShowcaseState }) {
  const items =
    state === "disabled"
      ? CONTEXT_ITEMS.map((item) => ({
          ...item,
          disabled: true,
          disabledReason: "This fixture is unavailable in the current state",
        }))
      : CONTEXT_ITEMS.slice(0, 3)
  return (
    <ContextRail
      title="Scenario runs"
      items={items}
      selectedId={state === "active" ? "run-023" : "run-024"}
      state={surfaceStateFor(state)}
      onSelect={() => undefined}
      onRetry={() => undefined}
    />
  )
}

function StatusChipExample({ state }: { readonly state: ShowcaseState }) {
  const [pressed, setPressed] = useState(state === "active")
  return (
    <StatusChip
      tone={stateTone(state)}
      label={pressed ? "Selected" : state === "demo" ? "Synthetic demo" : state}
      metadata="fixture"
      disabled={state === "disabled" || state === "loading"}
      pressed={pressed}
      onPress={() => setPressed((current) => !current)}
    />
  )
}

export function ShowcaseFoundation() {
  return (
    <div className="showcaseStack">
      <ShowcaseStateSection
        primitive="AppShell"
        description="The bounded shell keeps navigation, command chrome, and route scroll ownership visible."
      >
        {(state) => <AppShellExample state={state} />}
      </ShowcaseStateSection>
      <ShowcaseStateSection
        primitive="CommandBar"
        description="Command actions expose freshness, safe next steps, and state announcements."
      >
        {(state) => <CommandBarExample state={state} />}
      </ShowcaseStateSection>
      <ShowcaseStateSection
        primitive="ContextRail"
        description="The list-detail rail keeps selection, disabled reasons, and freshness in context."
      >
        {(state) => <ContextRailExample state={state} />}
      </ShowcaseStateSection>
      <ShowcaseStateSection
        primitive="StatusChip"
        description="Every status pairs semantic text and iconography with a tokenized tone."
      >
        {(state) => <StatusChipExample state={state} />}
      </ShowcaseStateSection>
    </div>
  )
}
