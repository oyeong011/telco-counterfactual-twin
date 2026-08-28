import { CircleAlert, Clock3, Info, type LucideIcon, TriangleAlert } from "lucide-react"
import { useId } from "react"
import { ErrorState } from "./ErrorState"
import { SURFACE_TONES, type SurfaceState } from "./primitiveTypes"
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
  readonly selectedEventId?: string
  readonly highlightedEventId?: string
  readonly onSelectEvent?: (id: string) => void
  readonly onHighlightEvent?: (id: string | undefined) => void
  readonly onRetry?: () => void
}

const SEVERITY_ICONS = {
  info: Info,
  warning: TriangleAlert,
  critical: CircleAlert,
} satisfies Record<TimelineEvent["severity"], LucideIcon>

export function EventTimeline({
  title,
  events,
  state = "default",
  selectedEventId,
  highlightedEventId,
  onSelectEvent,
  onHighlightEvent,
  onRetry,
}: EventTimelineProps) {
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
    <section className="panel timelinePanel" data-state={state} aria-labelledby={headingId}>
      <div className="panelHeader">
        <h2 id={headingId}>{title}</h2>
        <StatusChip
          tone={state === "demo" ? "demo" : SURFACE_TONES[state]}
          label={state === "demo" ? "Simulated events" : state}
        />
      </div>
      {state === "empty" || events.length === 0 ? (
        <p className="emptyMessage">No events were recorded.</p>
      ) : (
        <ol className="eventTimeline" aria-label={title}>
          {events.map((event) => {
            const Icon = SEVERITY_ICONS[event.severity]
            return (
              <li
                key={event.id}
                data-severity={event.severity}
                data-state={state}
                data-selected={event.id === selectedEventId || undefined}
                data-highlighted={event.id === highlightedEventId || undefined}
              >
                <time className="mono">
                  <Clock3 aria-hidden="true" />
                  {event.timestamp}
                </time>
                <button
                  type="button"
                  className="timelineEvent"
                  aria-label={`Select event ${event.type}`}
                  aria-pressed={event.id === selectedEventId}
                  data-highlighted={event.id === highlightedEventId || undefined}
                  disabled={state === "disabled"}
                  onClick={() => onSelectEvent?.(event.id)}
                  onPointerEnter={() => onHighlightEvent?.(event.id)}
                  onPointerLeave={() => onHighlightEvent?.(undefined)}
                  onFocus={() => onHighlightEvent?.(event.id)}
                  onBlur={() => onHighlightEvent?.(undefined)}
                >
                  <Icon aria-hidden="true" />
                  {event.type}
                </button>
                <span>{event.impacted}</span>
                <a
                  href={`#${event.evidenceId}`}
                  aria-disabled={state === "disabled" ? "true" : undefined}
                  tabIndex={state === "disabled" ? -1 : undefined}
                >
                  Evidence {event.evidenceId}
                </a>
              </li>
            )
          })}
        </ol>
      )}
    </section>
  )
}
