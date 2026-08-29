import { Clipboard, FileCode2 } from "lucide-react"
import { useId } from "react"
import { ErrorState } from "./ErrorState"
import { SURFACE_TONES, type SurfaceState } from "./primitiveTypes"
import { Skeleton } from "./Skeleton"
import { StatusChip, type StatusTone } from "./StatusChip"

export type PatchLine = {
  readonly id: string
  readonly number: number
  readonly kind: "addition" | "removal" | "context"
  readonly content: string
}

type TypedPatchDiffProps = {
  readonly path: string
  readonly schemaVersion: string
  readonly state?: SurfaceState
  readonly validationSummary: string
  readonly lines: readonly PatchLine[]
  readonly selectedLineId?: string
  readonly highlightedLineId?: string
  readonly onSelectLine?: (id: string) => void
  readonly onHighlightLine?: (id: string | undefined) => void
  readonly onCopy?: () => void
  readonly copyDisabled?: boolean
  readonly onRetry?: () => void
}

const LINE_LABELS = {
  addition: "Addition",
  removal: "Removal",
  context: "Context",
} satisfies Record<PatchLine["kind"], string>

export function TypedPatchDiff({
  path,
  schemaVersion,
  state = "default",
  validationSummary,
  lines,
  selectedLineId,
  highlightedLineId,
  onSelectLine,
  onHighlightLine,
  onCopy,
  copyDisabled = false,
  onRetry,
}: TypedPatchDiffProps) {
  const headingId = useId()

  if (state === "loading") {
    return <Skeleton variant="code" label="Loading typed patch" />
  }
  if (state === "error") {
    return (
      <ErrorState
        title="Typed patch unavailable"
        code="PATCH_INVALID"
        detail="The proposed patch failed schema validation."
        {...(onRetry ? { onRetry } : {})}
      />
    )
  }
  const tone: StatusTone = SURFACE_TONES[state]

  return (
    <section className="panel patchDiff" data-state={state} aria-labelledby={headingId}>
      <div className="panelHeader patchHeader">
        <div>
          <h2 id={headingId}>
            <FileCode2 aria-hidden="true" />
            Proposed typed patch
          </h2>
          <p className="mono">{path}</p>
        </div>
        <StatusChip tone={tone} label={state} metadata={schemaVersion} />
      </div>
      {state === "empty" || lines.length === 0 ? (
        <p className="emptyMessage">No patch was proposed.</p>
      ) : (
        // biome-ignore lint/a11y/noNoninteractiveTabindex: The scrollable list needs a Safari keyboard entry point.
        <ol className="patchLines" aria-label={`${path} patch lines`} tabIndex={0}>
          {lines.map((line) => {
            const content = (
              <>
                <span className="patchLineNumber">{line.number}</span>
                <code>
                  <span className="visuallyHidden">{LINE_LABELS[line.kind]}: </span>
                  <span aria-hidden="true">
                    {LINE_LABELS[line.kind]}: {line.content}
                  </span>
                </code>
              </>
            )
            return (
              <li
                key={line.id}
                data-kind={line.kind}
                data-selected={line.id === selectedLineId || undefined}
                data-highlighted={line.id === highlightedLineId || undefined}
              >
                {onSelectLine ? (
                  <button
                    type="button"
                    className="patchLineButton"
                    aria-label={`Select line ${line.number} ${LINE_LABELS[line.kind]}`}
                    aria-pressed={line.id === selectedLineId}
                    disabled={state === "disabled"}
                    onClick={() => onSelectLine(line.id)}
                    onPointerEnter={() => onHighlightLine?.(line.id)}
                    onPointerLeave={() => onHighlightLine?.(undefined)}
                    onFocus={() => onHighlightLine?.(line.id)}
                    onBlur={() => onHighlightLine?.(undefined)}
                  >
                    {content}
                  </button>
                ) : (
                  <div className="patchLineStatic">{content}</div>
                )}
              </li>
            )
          })}
        </ol>
      )}
      <footer className="patchFooter">
        <span>{validationSummary}</span>
        {onCopy ? (
          <button type="button" disabled={copyDisabled} onClick={onCopy}>
            <Clipboard aria-hidden="true" />
            Copy patch
          </button>
        ) : null}
      </footer>
    </section>
  )
}
