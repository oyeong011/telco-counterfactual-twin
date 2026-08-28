import { Download, MoonStar } from "lucide-react"
import { useState } from "react"
import { AppShell } from "../design/primitives/AppShell"
import { CommandBar } from "../design/primitives/CommandBar"
import { ContextRail } from "../design/primitives/ContextRail"
import { EvidenceRail } from "../design/primitives/EvidenceRail"
import { StatusChip } from "../design/primitives/StatusChip"
import { useTheme } from "../design/theme/ThemeProvider"
import { ThemePreferenceSchema } from "../design/theme/theme"
import { ShowcaseData } from "./ShowcaseData"
import { ShowcaseEvidence } from "./ShowcaseEvidence"
import { ShowcaseStates } from "./ShowcaseStates"
import { CONTEXT_ITEMS, EVIDENCE_FIELDS, SHOWCASE_NAVIGATION } from "./showcaseFixtures"

export function PrimitiveShowcase() {
  const theme = useTheme()
  const [selectedId, setSelectedId] = useState("run-024")
  const themeControl = (
    <label className="themeControl">
      <MoonStar aria-hidden="true" />
      <span>Theme</span>
      <select
        value={theme.preference}
        onChange={(event) =>
          theme.setPreference(ThemePreferenceSchema.parse(event.currentTarget.value))
        }
      >
        <option value="system">System</option>
        <option value="light">Light</option>
        <option value="dark">Dark</option>
      </select>
    </label>
  )
  const commandBar = (
    <CommandBar
      title="Primitive showcase"
      status={{ tone: "stale", label: "Observation stale", metadata: "42m" }}
      announcement="Synthetic demo state is active"
      actions={
        <button type="button" disabled title="Export is unavailable for synthetic fixtures">
          <Download aria-hidden="true" />
          Export
        </button>
      }
    >
      <StatusChip tone="demo" label="Synthetic demo" />
      {themeControl}
    </CommandBar>
  )
  const contextRail = (
    <ContextRail
      title="Run navigator"
      items={CONTEXT_ITEMS}
      selectedId={selectedId}
      state="demo"
      onSelect={setSelectedId}
    />
  )
  const evidenceRail = (
    <EvidenceRail title="Selected evidence" state="approved" fields={EVIDENCE_FIELDS} />
  )

  return (
    <AppShell
      navigation={SHOWCASE_NAVIGATION}
      commandBar={commandBar}
      contextRail={contextRail}
      evidenceRail={evidenceRail}
    >
      <div className="showcasePage">
        <header className="showcaseIntro">
          <div>
            <StatusChip tone="info" label="Development only" />
            <h1>Evidence-first console primitives</h1>
          </div>
          <p>
            Reusable states for a deterministic counterfactual twin. Every sample is synthetic and
            carries no network mutation authority.
          </p>
        </header>
        <ShowcaseStates />
        <ShowcaseData />
        <ShowcaseEvidence />
      </div>
    </AppShell>
  )
}
