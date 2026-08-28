import { DataTable, type DataTableColumn } from "./DataTable"
import type { SurfaceState } from "./primitiveTypes"
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
  readonly direction: "improved" | "degraded" | "neutral"
}

type MetricDeltaProps = {
  readonly title: string
  readonly series: readonly MetricSeries[]
  readonly rows: readonly MetricDeltaRow[]
  readonly state?: SurfaceState
}

const METRIC_COLUMNS = [
  { id: "metric", header: "Metric", render: (row: MetricDeltaRow) => row.metric },
  { id: "baseline", header: "Baseline", render: (row: MetricDeltaRow) => row.baseline },
  { id: "candidate", header: "Candidate", render: (row: MetricDeltaRow) => row.candidate },
  { id: "delta", header: "Delta", render: (row: MetricDeltaRow) => row.delta },
  { id: "direction", header: "Impact", render: (row: MetricDeltaRow) => row.direction },
] satisfies readonly DataTableColumn<MetricDeltaRow>[]

function seriesPoints(values: readonly number[]): string {
  return values
    .map((value, index) => {
      const x = values.length < 2 ? 50 : (index / (values.length - 1)) * 100
      const y = 100 - value
      return `${x},${y}`
    })
    .join(" ")
}

export function MetricDelta({ title, series, rows, state = "default" }: MetricDeltaProps) {
  return (
    <section className="panel metricDelta" aria-labelledby="metric-title">
      <div className="panelHeader">
        <h2 id="metric-title">{title}</h2>
        <StatusChip tone="proof" label="Deterministic benchmark" />
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
        columns={METRIC_COLUMNS}
        rows={rows}
        rowKey={(row) => row.id}
        state={state}
      />
    </section>
  )
}
