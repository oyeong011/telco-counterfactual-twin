import { CircleAlert, Clock3, Info, type LucideIcon, TriangleAlert } from "lucide-react"
import { useId } from "react"
import { ErrorState } from "./ErrorState"
import type { SurfaceState } from "./primitiveTypes"
import { Skeleton } from "./Skeleton"
import { StatusChip } from "./StatusChip"

export type TimelineEvent = {
  readonly id: string
  readonly timestamp: string
  readonly type: string
  readonly impacted: string
  readonly severity: "info" | "warning" | "critical"
  readonly evidenceId: string
}

type EventTimelineProps = {
  readonly title: string
  readonly events: readonly TimelineEvent[]
  readonly state?: SurfaceState
  readonly onRetry?: () => void
}

const SEVERITY_ICONS = {
  info: Info,
  warning: TriangleAlert,
  critical: CircleAlert,
} satisfies Record<TimelineEvent["severity"], LucideIcon>

export function EventTimeline({ title, events, state = "default", onRetry }: EventTimelineProps) {
  const headingId = useId()

  if (state === "loading") {
    return <Skeleton variant="timeline" label={`Loading ${title}`} />
  }
  if (state === "error") {
    return (
      <ErrorState
        title={`${title} unavailable`}
        code="TIMELINE_UNAVAILABLE"
        detail="The simulation event trace could not be read."
        {...(onRetry ? { onRetry } : {})}
      />
    )
  }

  return (
    <section className="panel timelinePanel" aria-labelledby={headingId}>
      <div className="panelHeader">
        <h2 id={headingId}>{title}</h2>
        {state === "demo" ? <StatusChip tone="demo" label="Simulated events" /> : null}
      </div>
      {state === "empty" || events.length === 0 ? (
        <p className="emptyMessage">No events were recorded.</p>
      ) : (
        <ol className="eventTimeline" aria-label={title}>
          {events.map((event) => {
            const Icon = SEVERITY_ICONS[event.severity]
            return (
              <li key={event.id} data-severity={event.severity} data-state={state}>
                <time className="mono">
                  <Clock3 aria-hidden="true" />
                  {event.timestamp}
                </time>
                <span className="timelineEvent">
                  <Icon aria-hidden="true" />
                  {event.type}
                </span>
                <span>{event.impacted}</span>
                <a href={`#${event.evidenceId}`}>Evidence {event.evidenceId}</a>
              </li>
            )
          })}
        </ol>
      )}
    </section>
  )
}
