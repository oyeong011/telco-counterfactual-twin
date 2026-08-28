import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"
import { DataTable } from "./DataTable"
import { MetricDelta } from "./MetricDelta"
import { TopologyCanvas } from "./TopologyCanvas"

const metricRows = [
  { id: "throughput", metric: "DL throughput", baseline: "142.3", candidate: "167.8" },
] as const

const metricColumns = [
  { id: "metric", header: "Metric", render: (row: (typeof metricRows)[number]) => row.metric },
  {
    id: "baseline",
    header: "Baseline",
    render: (row: (typeof metricRows)[number]) => row.baseline,
  },
  {
    id: "candidate",
    header: "Candidate",
    render: (row: (typeof metricRows)[number]) => row.candidate,
  },
] as const

describe("data primitives", () => {
  it("renders a semantic sortable table with an explicit caption", async () => {
    // Given
    const user = userEvent.setup()
    const onSort = vi.fn()
    render(
      <DataTable
        caption="Counterfactual metrics"
        columns={metricColumns}
        rows={metricRows}
        rowKey={(row) => row.id}
        sort={{ columnId: "metric", direction: "ascending", onSort }}
      />,
    )

    // When
    await user.click(screen.getByRole("button", { name: "Sort by Metric" }))

    // Then
    expect(screen.getByRole("table", { name: "Counterfactual metrics" })).toBeInTheDocument()
    expect(
      screen.getByRole("region", { name: "Counterfactual metrics scroll area" }),
    ).toHaveAttribute("tabindex", "0")
    expect(screen.getByRole("columnheader", { name: /Metric/ })).toHaveAttribute(
      "aria-sort",
      "ascending",
    )
    expect(onSort).toHaveBeenCalledWith("metric")
  })

  it("keeps an adjacency table available beside the topology graphic", async () => {
    // Given
    const user = userEvent.setup()
    const onSelectNode = vi.fn()
    render(
      <TopologyCanvas
        title="Synthetic core topology"
        nodes={[
          { id: "core", label: "Core router", x: 24, y: 30, status: "approved" },
          { id: "site-c", label: "Site C", x: 76, y: 70, status: "stale" },
        ]}
        edges={[
          {
            id: "core-site-c",
            sourceId: "core",
            targetId: "site-c",
            linkType: "backhaul",
            status: "rejected",
            impact: "high",
            evidenceId: "ev-demo-01",
          },
        ]}
        onSelectNode={onSelectNode}
      />,
    )

    // When
    screen.getByRole("button", { name: "Core router, approved" }).focus()
    await user.keyboard("{Enter}")

    // Then
    expect(onSelectNode).toHaveBeenCalledWith("core")
    expect(screen.getByRole("table", { name: "Topology adjacency" })).toBeInTheDocument()
    expect(screen.getByRole("cell", { name: "ev-demo-01" })).toBeInTheDocument()
  })

  it("pairs solid and dashed metric lines with an exact-value table", () => {
    // Given
    const series = [
      { label: "Baseline", style: "dashed", values: [82, 88, 81, 90] },
      { label: "Candidate", style: "solid", values: [84, 92, 89, 96] },
    ] as const

    // When
    const { container } = render(
      <MetricDelta
        title="Baseline versus candidate"
        series={series}
        rows={[
          {
            id: "p95",
            metric: "P95 throughput",
            baseline: "142.3 Mbps",
            candidate: "167.8 Mbps",
            delta: "+17.9%",
            direction: "improved",
          },
        ]}
      />,
    )

    // Then
    expect(screen.getByRole("img", { name: "Baseline versus candidate line chart" })).toBeVisible()
    expect(container.querySelector('[data-line-style="dashed"]')).toBeInTheDocument()
    expect(container.querySelector('[data-line-style="solid"]')).toBeInTheDocument()
    const table = screen.getByRole("table", { name: "Baseline versus candidate values" })
    expect(within(table).getByRole("cell", { name: "improved" })).toBeInTheDocument()
  })
})
