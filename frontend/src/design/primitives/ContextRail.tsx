import { ErrorState } from "./ErrorState"
import type { SurfaceState } from "./primitiveTypes"
import { Skeleton } from "./Skeleton"
import { StatusChip, type StatusTone } from "./StatusChip"

export type ContextRailItem = {
  readonly id: string
  readonly label: string
  readonly metadata: string
  readonly tone?: StatusTone
  readonly disabled?: boolean
  readonly disabledReason?: string
}

type ContextRailProps = {
  readonly title: string
  readonly items: readonly ContextRailItem[]
  readonly selectedId?: string
  readonly state?: SurfaceState
  readonly onSelect?: (id: string) => void
  readonly onRetry?: () => void
}

export function ContextRail({
  title,
  items,
  selectedId,
  state = "default",
  onSelect,
  onRetry,
}: ContextRailProps) {
  return (
    <section aria-label={title}>
      <div className="railHeader">
        <h2>{title}</h2>
      </div>
      {state === "loading" ? <Skeleton variant="table" label={`Loading ${title}`} /> : null}
      {state === "error" ? (
        <ErrorState
          title={`${title} unavailable`}
          code="RAIL_UNAVAILABLE"
          detail="The contextual list could not be loaded."
          {...(onRetry ? { onRetry } : {})}
        />
      ) : null}
      {state === "empty" ? <p className="emptyMessage">No items available.</p> : null}
      {state !== "loading" && state !== "error" && state !== "empty" ? (
        <ul className="railList">
          {items.map((item) => (
            <li key={item.id}>
              <button
                type="button"
                className="railButton"
                aria-pressed={item.id === selectedId}
                disabled={item.disabled}
                title={item.disabledReason}
                onClick={() => onSelect?.(item.id)}
              >
                <span className="railLabel" title={item.label}>
                  {item.label}
                </span>
                {item.tone ? (
                  <StatusChip
                    tone={item.tone}
                    label={item.metadata}
                    {...(item.disabled === undefined ? {} : { disabled: item.disabled })}
                  />
                ) : (
                  <span className="mono">{item.metadata}</span>
                )}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  )
}
