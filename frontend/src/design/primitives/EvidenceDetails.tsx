import { Copy, FileCheck2 } from "lucide-react"
import { SURFACE_TONES, type SurfaceState } from "./primitiveTypes"
import { StatusChip, type StatusTone } from "./StatusChip"

export type EvidenceField = {
  readonly id: string
  readonly label: string
  readonly value: string
}

export type EvidenceAction = "copy"

type EvidenceDetailsProps = {
  readonly title: string
  readonly state: SurfaceState
  readonly fields: readonly EvidenceField[]
  readonly selectedArtifactId: string | undefined
  readonly highlightedArtifactId: string | undefined
  readonly selectedAction: EvidenceAction | undefined
  readonly onSelectArtifact: ((id: string) => void) | undefined
  readonly onHighlightArtifact: ((id: string | undefined) => void) | undefined
  readonly onCopy: (() => void) | undefined
  readonly copyDisabled: boolean
  readonly headingId: string
}

export function EvidenceDetails({
  title,
  state,
  fields,
  selectedArtifactId,
  highlightedArtifactId,
  selectedAction,
  onSelectArtifact,
  onHighlightArtifact,
  onCopy,
  copyDisabled,
  headingId,
}: EvidenceDetailsProps) {
  const tone: StatusTone = SURFACE_TONES[state]

  return (
    <>
      <div className="panelHeader">
        <h2 id={headingId}>
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
            <div
              key={field.id}
              data-selected={field.id === selectedArtifactId || undefined}
              data-highlighted={field.id === highlightedArtifactId || undefined}
            >
              <dt>
                {onSelectArtifact ? (
                  <button
                    type="button"
                    className="evidenceArtifactButton"
                    aria-label={`Select ${field.label}`}
                    aria-pressed={field.id === selectedArtifactId}
                    disabled={state === "disabled"}
                    onClick={() => onSelectArtifact(field.id)}
                    onPointerEnter={() => onHighlightArtifact?.(field.id)}
                    onPointerLeave={() => onHighlightArtifact?.(undefined)}
                    onFocus={() => onHighlightArtifact?.(field.id)}
                    onBlur={() => onHighlightArtifact?.(undefined)}
                  >
                    {field.label}
                  </button>
                ) : (
                  field.label
                )}
              </dt>
              <dd className="mono">{field.value}</dd>
            </div>
          ))}
        </dl>
      )}
      {onCopy ? (
        <button
          className="evidenceAction"
          type="button"
          disabled={copyDisabled || state === "disabled"}
          aria-pressed={selectedAction === "copy"}
          onClick={onCopy}
        >
          <Copy aria-hidden="true" />
          Copy evidence hash
        </button>
      ) : null}
    </>
  )
}
