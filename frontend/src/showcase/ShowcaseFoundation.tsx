import { Activity, Network } from "lucide-react"
import { AppShell } from "../design/primitives/AppShell"
import { CommandBar } from "../design/primitives/CommandBar"
import { ContextRail } from "../design/primitives/ContextRail"
import { StatusChip } from "../design/primitives/StatusChip"
import { type ShowcaseState, surfaceStateFor } from "./primitiveStateRegistry"
import { ShowcaseStateSection } from "./ShowcaseStates"
import { CONTEXT_ITEMS } from "./showcaseFixtures"
import { stateTone } from "./showcaseStateTone"

const PREVIEW_NAVIGATION = [
  { label: "Workbench", href: "#preview-workbench", icon: Network, active: true },
  { label: "Activity", href: "#preview-activity", icon: Activity, active: false },
] as const

function AppShellExample({ state }: { readonly state: ShowcaseState }) {
  return (
    <AppShell
      preview
      navigation={PREVIEW_NAVIGATION}
      commandBar={
        <CommandBar
          title="Shell preview"
          status={{ tone: stateTone(state), label: state }}
          announcement={`AppShell ${state} state`}
        />
      }
    >
      <p className="showcasePreviewCopy">Bounded route body · {state} chrome</p>
    </AppShell>
  )
}

function CommandBarExample({ state }: { readonly state: ShowcaseState }) {
  return (
    <CommandBar
      title="Route command"
      status={{ tone: stateTone(state), label: state, metadata: "fixture" }}
      announcement={`Command bar ${state} state`}
      actions={
        <button type="button" disabled={state === "disabled"}>
          Review
        </button>
      }
    />
  )
}

function ContextRailExample({ state }: { readonly state: ShowcaseState }) {
  return (
    <ContextRail
      title="Scenario runs"
      items={CONTEXT_ITEMS.slice(0, 2)}
      selectedId="run-024"
      state={surfaceStateFor(state)}
    />
  )
}

function StatusChipExample({ state }: { readonly state: ShowcaseState }) {
  return (
    <StatusChip
      tone={stateTone(state)}
      label={state === "demo" ? "Synthetic demo" : state}
      metadata="fixture"
      disabled={state === "disabled"}
      pressed={state === "active"}
      onPress={() => undefined}
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
