import { CircleAlert, RotateCcw } from "lucide-react"

type ErrorStateProps = {
  readonly title: string
  readonly code: string
  readonly detail: string
  readonly requestId?: string
  readonly blocking?: boolean
  readonly retryDisabled?: boolean
  readonly retryLabel?: string
  readonly onRetry?: () => void
}

export function ErrorState({
  title,
  code,
  detail,
  requestId,
  blocking = false,
  retryDisabled = false,
  retryLabel = "Retry evidence",
  onRetry,
}: ErrorStateProps) {
  return (
    <section
      className="errorState"
      data-layout="component-aware"
      role={blocking ? "alert" : "status"}
      aria-label={title}
    >
      <CircleAlert aria-hidden="true" className="errorStateIcon" />
      <div>
        <h3>{title}</h3>
        <p className="errorCode">{code}</p>
        <p>{detail}</p>
        {requestId ? <p className="mono">Request {requestId}</p> : null}
      </div>
      {onRetry ? (
        <button type="button" disabled={retryDisabled} onClick={onRetry}>
          <RotateCcw aria-hidden="true" />
          {retryLabel}
        </button>
      ) : null}
    </section>
  )
}
