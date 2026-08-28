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
  readonly selectedNodeId?: string
  readonly highlightedNodeId?: string
  readonly onSelectNode?: (id: string) => void
  readonly onHighlightNode?: (id: string | undefined) => void
  readonly onRetry?: () => void
}

type TopologyLabelGeometry = {
  readonly x: number
  readonly y: number
  readonly width: number
}

const LABEL_FONT_SIZE = 4
const LABEL_STROKE_WIDTH = 1.5
const LABEL_HEIGHT = 6

const EDGE_COLUMNS = [
  { id: "source", header: "Source", render: (edge: TopologyEdge) => edge.sourceId },
  { id: "target", header: "Target", render: (edge: TopologyEdge) => edge.targetId },
  { id: "type", header: "Link type", render: (edge: TopologyEdge) => edge.linkType },
  { id: "status", header: "Status", render: (edge: TopologyEdge) => edge.status },
  { id: "impact", header: "Impact", render: (edge: TopologyEdge) => edge.impact },
  { id: "evidence", header: "Evidence ID", render: (edge: TopologyEdge) => edge.evidenceId },
] satisfies readonly DataTableColumn<TopologyEdge>[]

function labelGeometry(node: TopologyNode): TopologyLabelGeometry {
  const width = Math.max(12, node.label.length * 2.5 + 4)
  if (node.y <= 25) return { x: node.x, y: 5, width }
  if (node.y >= 70) return { x: node.x, y: 100, width }
  return { x: node.x < 50 ? node.x - 18 : node.x + 18, y: node.y - 12, width }
}

export function TopologyCanvas({
  title,
  nodes,
  edges,
  state = "default",
  selectedNodeId,
  highlightedNodeId,
  onSelectNode,
  onHighlightNode,
  onRetry,
}: TopologyCanvasProps) {
  const headingId = useId()
  const selectedNode = nodes.find((node) => node.id === selectedNodeId)
  const highlightedNode = nodes.find((node) => node.id === highlightedNodeId)

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
          <svg viewBox="0 0 100 108" role="img" aria-label={`${title} graph`}>
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
                data-selected={node.id === selectedNodeId || undefined}
                data-highlighted={node.id === highlightedNodeId || undefined}
                transform={`translate(${node.x} ${node.y})`}
              >
                <circle r="7" />
                <Network aria-hidden="true" x="-4" y="-4" width="8" height="8" />
              </g>
            ))}
            {nodes.map((node) => {
              const label = labelGeometry(node)
              return (
                <g
                  key={`${node.id}-label`}
                  className="topologyLabel"
                  data-topology-label={node.id}
                  data-selected={node.id === selectedNodeId || undefined}
                  data-highlighted={node.id === highlightedNodeId || undefined}
                >
                  <rect
                    x={label.x - label.width / 2}
                    y={label.y - 4}
                    width={label.width}
                    height={LABEL_HEIGHT}
                    rx="1"
                  />
                  <text
                    x={label.x}
                    y={label.y}
                    textAnchor="middle"
                    fontSize={LABEL_FONT_SIZE}
                    strokeWidth={LABEL_STROKE_WIDTH}
                    paintOrder="stroke fill"
                  >
                    {node.label}
                  </text>
                </g>
              )
            })}
          </svg>
          <fieldset className="topologyNodeControls">
            <legend className="visuallyHidden">Topology nodes</legend>
            {nodes.map((node) => (
              <button
                key={node.id}
                type="button"
                className="topologyNodeButton"
                aria-pressed={node.id === selectedNodeId}
                data-highlighted={node.id === highlightedNodeId || undefined}
                disabled={state === "disabled"}
                onClick={() => onSelectNode?.(node.id)}
                onPointerEnter={() => onHighlightNode?.(node.id)}
                onPointerLeave={() => onHighlightNode?.(undefined)}
                onFocus={() => onHighlightNode?.(node.id)}
                onBlur={() => onHighlightNode?.(undefined)}
              >
                {node.label}, {node.status}
              </button>
            ))}
          </fieldset>
          <div className="topologySelection" aria-live="polite">
            <span>Selected node: {selectedNode?.label ?? "None"}</span>
            {highlightedNode ? <span>Highlighted node: {highlightedNode.label}</span> : null}
          </div>
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
