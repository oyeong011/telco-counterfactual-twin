import { Copy, FileCheck2 } from "lucide-react"
import { ErrorState } from "./ErrorState"
import { SURFACE_TONES, type SurfaceState } from "./primitiveTypes"
import { Skeleton } from "./Skeleton"
import { StatusChip, type StatusTone } from "./StatusChip"

export type EvidenceField = {
  readonly label: string
  readonly value: string
}

type EvidenceRailProps = {
  readonly title: string
  readonly state?: SurfaceState
  readonly fields: readonly EvidenceField[]
  readonly onCopy?: () => void
  readonly onRetry?: () => void
}

export function EvidenceRail({
  title,
  state = "default",
  fields,
  onCopy,
  onRetry,
}: EvidenceRailProps) {
  if (state === "loading") {
    return <Skeleton variant="evidence" label={`Loading ${title}`} />
  }
  if (state === "error") {
    return (
      <ErrorState
        title={`${title} unavailable`}
        code="EVIDENCE_UNAVAILABLE"
        detail="The signed evidence package could not be opened."
        {...(onRetry ? { onRetry } : {})}
      />
    )
  }
  const tone: StatusTone = SURFACE_TONES[state]

  return (
    <aside className="evidencePanel" aria-label={title}>
      <div className="panelHeader">
        <h2>
          <FileCheck2 aria-hidden="true" />
          {title}
        </h2>
        <StatusChip tone={tone} label={state} />
      </div>
      {state === "empty" || fields.length === 0 ? (
        <p className="emptyMessage">No evidence selected.</p>
      ) : (
        <dl className="evidenceFields">
          {fields.map((field) => (
            <div key={field.label}>
              <dt>{field.label}</dt>
              <dd className="mono">{field.value}</dd>
            </div>
          ))}
        </dl>
      )}
      {onCopy ? (
        <button className="evidenceAction" type="button" onClick={onCopy}>
          <Copy aria-hidden="true" />
          Copy evidence hash
        </button>
      ) : null}
    </aside>
  )
}
