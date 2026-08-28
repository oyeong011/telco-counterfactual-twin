import { FileCheck2, X } from "lucide-react"
import { useEffect, useId, useRef, useState } from "react"
import { ErrorState } from "./ErrorState"
import { type EvidenceAction, EvidenceDetails, type EvidenceField } from "./EvidenceDetails"
import type { SurfaceState } from "./primitiveTypes"
import { Skeleton } from "./Skeleton"

export type { EvidenceField } from "./EvidenceDetails"

type EvidenceRailProps = {
  readonly title: string
  readonly state?: SurfaceState
  readonly fields: readonly EvidenceField[]
  readonly selectedArtifactId?: string
  readonly highlightedArtifactId?: string
  readonly selectedAction?: EvidenceAction
  readonly onSelectArtifact?: (id: string) => void
  readonly onHighlightArtifact?: (id: string | undefined) => void
  readonly onCopy?: () => void
  readonly copyDisabled?: boolean
  readonly onRetry?: () => void
}

export function EvidenceRail({
  title,
  state = "default",
  fields,
  selectedArtifactId,
  highlightedArtifactId,
  selectedAction,
  onSelectArtifact,
  onHighlightArtifact,
  onCopy,
  copyDisabled = false,
  onRetry,
}: EvidenceRailProps) {
  const [isOpen, setIsOpen] = useState(false)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const dialogRef = useRef<HTMLDialogElement>(null)
  const wasOpenRef = useRef(false)
  const desktopHeadingId = useId()
  const dialogHeadingId = useId()

  useEffect(() => {
    const dialog = dialogRef.current
    if (dialog === null) return

    if (isOpen) {
      wasOpenRef.current = true
      if (!dialog.open) dialog.showModal()
      dialog.querySelector<HTMLElement>("[data-dialog-close]")?.focus()
      return
    }

    if (dialog.open) dialog.close()
    if (wasOpenRef.current) {
      wasOpenRef.current = false
      triggerRef.current?.focus()
    }
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

  const detailsProps = {
    state,
    fields,
    selectedArtifactId,
    highlightedArtifactId,
    selectedAction,
    onSelectArtifact,
    onHighlightArtifact,
    onCopy,
    copyDisabled,
  }

  return (
    <>
      <aside className="evidencePanel" data-state={state} aria-labelledby={desktopHeadingId}>
        <EvidenceDetails title={title} headingId={desktopHeadingId} {...detailsProps} />
      </aside>
      <button
        className="evidenceSheetTrigger"
        type="button"
        ref={triggerRef}
        data-state={state}
        aria-haspopup="dialog"
        aria-expanded={isOpen}
        aria-label={`Open ${title.toLowerCase()}`}
        onClick={() => setIsOpen(true)}
      >
        <FileCheck2 aria-hidden="true" />
        Open {title}
      </button>
      <dialog
        className="evidenceSheet"
        ref={dialogRef}
        aria-labelledby={dialogHeadingId}
        onCancel={(event) => {
          event.preventDefault()
          setIsOpen(false)
        }}
        onClose={() => setIsOpen(false)}
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
          headingId={`${dialogHeadingId}-details`}
          {...detailsProps}
        />
      </dialog>
    </>
  )
}
