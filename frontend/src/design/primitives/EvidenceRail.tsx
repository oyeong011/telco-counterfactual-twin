import { Copy, FileCheck2, X } from "lucide-react"
import { useEffect, useId, useRef, useState } from "react"
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

type EvidenceDetailsProps = {
  readonly title: string
  readonly state: SurfaceState
  readonly fields: readonly EvidenceField[]
  readonly onCopy?: () => void
  readonly headingId: string
}

function EvidenceDetails({ title, state, fields, onCopy, headingId }: EvidenceDetailsProps) {
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
    </>
  )
}

export function EvidenceRail({
  title,
  state = "default",
  fields,
  onCopy,
  onRetry,
}: EvidenceRailProps) {
  const [isOpen, setIsOpen] = useState(false)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const dialogRef = useRef<HTMLDialogElement>(null)
  const wasOpenRef = useRef(false)
  const desktopHeadingId = useId()
  const dialogHeadingId = useId()

  useEffect(() => {
    if (!isOpen) {
      if (wasOpenRef.current) {
        triggerRef.current?.focus()
      }
      wasOpenRef.current = false
      return
    }

    wasOpenRef.current = true
    const dialog = dialogRef.current
    const closeButton = dialog?.querySelector<HTMLElement>("[data-dialog-close]")
    closeButton?.focus()

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault()
        setIsOpen(false)
        return
      }
      if (event.key !== "Tab" || dialog === null) return

      const focusable = Array.from(
        dialog.querySelectorAll<HTMLElement>(
          "button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])",
        ),
      )
      const first = focusable.at(0)
      const last = focusable.at(-1)
      if (first === undefined || last === undefined) return
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }

    document.addEventListener("keydown", handleKeyDown)
    return () => document.removeEventListener("keydown", handleKeyDown)
  }, [isOpen])

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

  return (
    <>
      <aside className="evidencePanel" aria-labelledby={desktopHeadingId}>
        <EvidenceDetails
          title={title}
          state={state}
          fields={fields}
          {...(onCopy ? { onCopy } : {})}
          headingId={desktopHeadingId}
        />
      </aside>
      <button
        className="evidenceSheetTrigger"
        type="button"
        ref={triggerRef}
        aria-haspopup="dialog"
        aria-expanded={isOpen}
        aria-label={`Open ${title.toLowerCase()}`}
        onClick={() => setIsOpen(true)}
      >
        <FileCheck2 aria-hidden="true" />
        Open {title}
      </button>
      {isOpen ? (
        <dialog
          className="evidenceSheet"
          ref={dialogRef}
          open
          aria-modal="true"
          aria-labelledby={dialogHeadingId}
          onCancel={(event) => {
            event.preventDefault()
            setIsOpen(false)
          }}
        >
          <div className="evidenceSheetHeader">
            <h2 id={dialogHeadingId}>{title}</h2>
            <button
              className="evidenceSheetClose"
              type="button"
              data-dialog-close
              aria-label={`Close ${title.toLowerCase()}`}
              onClick={() => setIsOpen(false)}
            >
              <X aria-hidden="true" />
            </button>
          </div>
          <EvidenceDetails
            title="Evidence details"
            state={state}
            fields={fields}
            {...(onCopy ? { onCopy } : {})}
            headingId={`${dialogHeadingId}-details`}
          />
        </dialog>
      ) : null}
    </>
  )
}
