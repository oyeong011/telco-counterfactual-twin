import type { ReactNode } from "react"
import { DataTable, type DataTableColumn } from "../design/primitives/DataTable"
import { ErrorState } from "../design/primitives/ErrorState"
import {
  SKELETON_VARIANTS,
  SURFACE_STATES,
  type SurfaceState,
} from "../design/primitives/primitiveTypes"
import { Skeleton } from "../design/primitives/Skeleton"
import { StatusChip, type StatusTone } from "../design/primitives/StatusChip"

type StateRow = {
  readonly id: string
  readonly state: string
  readonly recovery: string
}

const STATE_COLUMNS = [
  { id: "state", header: "State", render: (row: StateRow) => row.state },
  { id: "recovery", header: "Visible recovery", render: (row: StateRow) => row.recovery },
] satisfies readonly DataTableColumn<StateRow>[]

const TONES = {
  default: "neutral",
  disabled: "neutral",
  loading: "loading",
  empty: "neutral",
  error: "danger",
  stale: "stale",
  rejected: "rejected",
  approved: "approved",
  demo: "demo",
} satisfies Record<SurfaceState, StatusTone>

const INTERACTION_STATES = ["default", "hover", "active", "focus", "disabled"] as const

function StateCell({ label, children }: { readonly label: string; readonly children: ReactNode }) {
  return (
    <div className="showcaseStateCell" data-preview={label}>
      <span className="showcaseStateLabel">{label}</span>
      {children}
    </div>
  )
}

export function ShowcaseStates() {
  return (
    <section className="showcaseStack" aria-labelledby="states-heading">
      <div className="showcaseSectionHeading">
        <h2 id="states-heading">Interaction and system state matrix</h2>
        <p>Visible labels, icons, and copy keep state independent from color.</p>
      </div>
      <section className="showcaseStateGrid" aria-label="Interactive control states">
        {INTERACTION_STATES.map((state) => (
          <StateCell key={state} label={state}>
            <StatusChip
              tone="info"
              label="Inspect evidence"
              disabled={state === "disabled"}
              pressed={state === "active"}
              onPress={() => undefined}
            />
          </StateCell>
        ))}
      </section>
      <section className="showcaseStateGrid" aria-label="System states">
        {SURFACE_STATES.map((state) => (
          <StateCell key={state} label={state}>
            <StatusChip tone={TONES[state]} label={state} metadata="Sample state" />
          </StateCell>
        ))}
      </section>
      <div className="showcaseGrid">
        <DataTable
          caption="Empty evidence table"
          columns={STATE_COLUMNS}
          rows={[]}
          rowKey={(row) => row.id}
          state="empty"
        />
        <DataTable
          caption="Stale evidence table"
          columns={STATE_COLUMNS}
          rows={[{ id: "stale", state: "Stale", recovery: "Refresh observation" }]}
          rowKey={(row) => row.id}
          state="stale"
        />
      </div>
      <div className="showcaseGrid">
        {SKELETON_VARIANTS.map((variant) => (
          <Skeleton key={variant} variant={variant} label={`Loading ${variant}`} rows={3} />
        ))}
      </div>
      <ErrorState
        title="Build identity mismatch"
        code="BUILD_IDENTITY_MISMATCH"
        detail="The console cannot bind this sample to the selected runtime identity."
        requestId="fixture-request-92"
      />
    </section>
  )
}
