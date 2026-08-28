import { Network } from "lucide-react"
import { useId } from "react"
import { DataTable, type DataTableColumn } from "./DataTable"
import { ErrorState } from "./ErrorState"
import { SURFACE_TONES, type SurfaceState } from "./primitiveTypes"
import { Skeleton } from "./Skeleton"
import { StatusChip } from "./StatusChip"

export type TopologyNode = {
  readonly id: string
  readonly label: string
  readonly x: number
  readonly y: number
  readonly status: "default" | "stale" | "rejected" | "approved"
}

export type TopologyEdge = {
  readonly id: string
  readonly sourceId: string
  readonly targetId: string
  readonly linkType: string
  readonly status: "default" | "stale" | "rejected" | "approved"
  readonly impact: string
  readonly evidenceId: string
}

type TopologyCanvasProps = {
  readonly title: string
  readonly nodes: readonly TopologyNode[]
  readonly edges: readonly TopologyEdge[]
  readonly state?: SurfaceState
  readonly onSelectNode?: (id: string) => void
  readonly onRetry?: () => void
}

const EDGE_COLUMNS = [
  { id: "source", header: "Source", render: (edge: TopologyEdge) => edge.sourceId },
  { id: "target", header: "Target", render: (edge: TopologyEdge) => edge.targetId },
  { id: "type", header: "Link type", render: (edge: TopologyEdge) => edge.linkType },
  { id: "status", header: "Status", render: (edge: TopologyEdge) => edge.status },
  { id: "impact", header: "Impact", render: (edge: TopologyEdge) => edge.impact },
  { id: "evidence", header: "Evidence ID", render: (edge: TopologyEdge) => edge.evidenceId },
] satisfies readonly DataTableColumn<TopologyEdge>[]

export function TopologyCanvas({
  title,
  nodes,
  edges,
  state = "default",
  onSelectNode,
  onRetry,
}: TopologyCanvasProps) {
  const headingId = useId()

  if (state === "loading") {
    return <Skeleton variant="topology" label={`Loading ${title}`} />
  }
  if (state === "error") {
    return (
      <section className="panel topologyPanel" data-state={state} aria-labelledby={headingId}>
        <div className="panelHeader">
          <h2 id={headingId}>{title}</h2>
          <StatusChip tone="danger" label="error" />
        </div>
        <ErrorState
          title={`${title} unavailable`}
          code="TOPOLOGY_UNAVAILABLE"
          detail="The graph failed to load; the last adjacency evidence remains available below."
          {...(onRetry ? { onRetry } : {})}
        />
        <DataTable
          caption="Topology adjacency"
          columns={EDGE_COLUMNS}
          rows={edges}
          rowKey={(edge) => edge.id}
        />
      </section>
    )
  }

  return (
    <section className="panel topologyPanel" data-state={state} aria-labelledby={headingId}>
      <div className="panelHeader">
        <h2 id={headingId}>{title}</h2>
        <StatusChip
          tone={state === "demo" ? "demo" : SURFACE_TONES[state]}
          label={state === "demo" ? "Synthetic demo" : state}
        />
      </div>
      {state === "empty" ? (
        <p className="emptyMessage">No topology snapshot is available.</p>
      ) : (
        <div className="topologyCanvas">
          <svg viewBox="0 0 100 100" role="img" aria-label={`${title} graph`}>
            <title>{title}</title>
            <desc>
              Keyboard traversable nodes with an adjacency table immediately after the graph.
            </desc>
            {edges.map((edge) => {
              const source = nodes.find((node) => node.id === edge.sourceId)
              const target = nodes.find((node) => node.id === edge.targetId)
              if (!source || !target) return null
              return (
                <line
                  key={edge.id}
                  className="topologyEdge"
                  data-status={edge.status}
                  x1={source.x}
                  y1={source.y}
                  x2={target.x}
                  y2={target.y}
                />
              )
            })}
            {nodes.map((node) => (
              <g
                key={node.id}
                className="topologyNode"
                data-status={node.status}
                transform={`translate(${node.x} ${node.y})`}
              >
                <circle r="7" />
                <Network aria-hidden="true" x="-4" y="-4" width="8" height="8" />
                <text x="0" y="12" textAnchor="middle">
                  {node.label}
                </text>
              </g>
            ))}
          </svg>
          <ul className="topologyNodeControls" aria-label="Topology nodes">
            {nodes.map((node) => (
              <li key={node.id}>
                <button
                  type="button"
                  className="topologyNodeButton"
                  disabled={state === "disabled"}
                  onClick={() => onSelectNode?.(node.id)}
                >
                  {node.label}, {node.status}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
      <DataTable
        caption="Topology adjacency"
        columns={EDGE_COLUMNS}
        rows={edges}
        rowKey={(edge) => edge.id}
        state={state === "empty" ? "empty" : state}
        {...(onRetry ? { onRetry } : {})}
      />
    </section>
  )
}
