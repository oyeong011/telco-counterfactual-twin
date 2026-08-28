import { Clipboard, FileCode2 } from "lucide-react"
import { SURFACE_TONES, type SurfaceState } from "./primitiveTypes"
import { Skeleton } from "./Skeleton"
import { StatusChip, type StatusTone } from "./StatusChip"

export type PatchLine = {
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
  readonly onCopy?: () => void
  readonly copyDisabled?: boolean
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
  onCopy,
  copyDisabled = false,
}: TypedPatchDiffProps) {
  if (state === "loading") {
    return <Skeleton variant="code" label="Loading typed patch" />
  }
  const tone: StatusTone = SURFACE_TONES[state]

  return (
    <section className="panel patchDiff" aria-labelledby="patch-title">
      <div className="panelHeader patchHeader">
        <div>
          <h2 id="patch-title">
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
        <ol className="patchLines" aria-label={`${path} patch lines`}>
          {lines.map((line) => (
            <li key={`${line.number}-${line.kind}`} data-kind={line.kind}>
              <span className="patchLineNumber">{line.number}</span>
              <code>
                <span className="visuallyHidden">{LINE_LABELS[line.kind]}: </span>
                <span aria-hidden="true">
                  {LINE_LABELS[line.kind]}: {line.content}
                </span>
              </code>
            </li>
          ))}
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
