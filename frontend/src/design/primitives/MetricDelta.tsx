import { useId } from "react"
import { DataTable, type DataTableColumn } from "./DataTable"
import { ErrorState } from "./ErrorState"
import { SURFACE_TONES, type SurfaceState } from "./primitiveTypes"
import { Skeleton } from "./Skeleton"
import { StatusChip } from "./StatusChip"

export type MetricSeries = {
  readonly label: string
  readonly style: "dashed" | "solid"
  readonly values: readonly number[]
}

export type MetricDeltaRow = {
  readonly id: string
  readonly metric: string
  readonly baseline: string
  readonly candidate: string
  readonly delta: string
  readonly direction: "changed" | "improved" | "degraded" | "neutral"
}

type MetricDeltaProps = {
  readonly title: string
  readonly series: readonly MetricSeries[]
  readonly rows: readonly MetricDeltaRow[]
  readonly state?: SurfaceState
  readonly selectedMetricId?: string
  readonly highlightedMetricId?: string
  readonly onSelectMetric?: (id: string) => void
  readonly onHighlightMetric?: (id: string | undefined) => void
  readonly onRetry?: () => void
}

function seriesPoints(values: readonly number[]): string {
  return values
    .map((value, index) => {
      const x = values.length < 2 ? 50 : (index / (values.length - 1)) * 100
      const y = 100 - value
      return `${x},${y}`
    })
    .join(" ")
}

export function MetricDelta({
  title,
  series,
  rows,
  state = "default",
  selectedMetricId,
  highlightedMetricId,
  onSelectMetric,
  onHighlightMetric,
  onRetry,
}: MetricDeltaProps) {
  const headingId = useId()

  if (state === "loading") {
    return <Skeleton variant="chart" label={`Loading ${title}`} />
  }

  const columns = [
    {
      id: "metric",
      header: "Metric",
      render: (row: MetricDeltaRow) =>
        onSelectMetric ? (
          <button
            type="button"
            className="metricSelectButton"
            aria-label={`Select metric ${row.metric}`}
            aria-pressed={row.id === selectedMetricId}
            data-highlighted={row.id === highlightedMetricId || undefined}
            disabled={state === "disabled"}
            onClick={() => onSelectMetric(row.id)}
            onPointerEnter={() => onHighlightMetric?.(row.id)}
            onPointerLeave={() => onHighlightMetric?.(undefined)}
            onFocus={() => onHighlightMetric?.(row.id)}
            onBlur={() => onHighlightMetric?.(undefined)}
          >
            {row.metric}
          </button>
        ) : (
          row.metric
        ),
    },
    { id: "baseline", header: "Baseline", render: (row: MetricDeltaRow) => row.baseline },
    { id: "candidate", header: "Candidate", render: (row: MetricDeltaRow) => row.candidate },
    { id: "delta", header: "Delta", render: (row: MetricDeltaRow) => row.delta },
    {
      id: "direction",
      header: "Interpretation",
      render: (row: MetricDeltaRow) => row.direction,
    },
  ] satisfies readonly DataTableColumn<MetricDeltaRow>[]
  if (state === "error") {
    return (
      <ErrorState
        title={`${title} unavailable`}
        code="METRIC_UNAVAILABLE"
        detail="The comparison values could not be calculated."
        {...(onRetry ? { onRetry } : {})}
      />
    )
  }

  return (
    <section className="panel metricDelta" data-state={state} aria-labelledby={headingId}>
      <div className="panelHeader">
        <h2 id={headingId}>{title}</h2>
        <StatusChip tone={SURFACE_TONES[state]} label={state} />
      </div>
      <div className="metricChartRegion">
        <svg viewBox="0 0 100 100" role="img" aria-label={`${title} line chart`}>
          <title>{title}</title>
          <desc>Baseline uses a dashed line. Candidate uses a solid line.</desc>
          <path className="chartGrid" d="M0 25 H100 M0 50 H100 M0 75 H100" />
          {series.map((item) => (
            <polyline
              key={item.label}
              className={`chartSeries chartSeries--${item.style}`}
              data-line-style={item.style}
              points={seriesPoints(item.values)}
            />
          ))}
        </svg>
        <ul className="chartLegend" aria-label="Line styles">
          {series.map((item) => (
            <li key={item.label}>
              <span className={`chartLegendLine chartSeries--${item.style}`} aria-hidden="true" />
              {item.label}, {item.style}
            </li>
          ))}
        </ul>
      </div>
      <DataTable
        caption={`${title} values`}
        columns={columns}
        rows={rows}
        rowKey={(row) => row.id}
        state={state}
        {...(onRetry ? { onRetry } : {})}
      />
    </section>
  )
}
