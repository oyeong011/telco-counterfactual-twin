import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"
import { ApprovalEvidence } from "./ApprovalEvidence"
import { ErrorState } from "./ErrorState"
import { EventTimeline } from "./EventTimeline"
import { EvidenceRail } from "./EvidenceRail"
import { Skeleton } from "./Skeleton"
import { StatusChip } from "./StatusChip"
import { TypedPatchDiff } from "./TypedPatchDiff"

describe("evidence primitives", () => {
  it("communicates approved status with visible text instead of color alone", () => {
    // Given
    const label = "Replay verified"

    // When
    render(<StatusChip tone="approved" label={label} metadata="Proof available" />)

    // Then
    expect(screen.getByText(label)).toBeVisible()
    expect(screen.getByText("Proof available")).toBeVisible()
  })

  it("provides a blocking error recovery action", async () => {
    // Given
    const user = userEvent.setup()
    const onRetry = vi.fn()
    render(
      <ErrorState
        title="Evidence unavailable"
        code="EVIDENCE_TIMEOUT"
        detail="The signed package did not arrive."
        requestId="req-demo-17"
        blocking
        onRetry={onRetry}
      />,
    )

    // When
    await user.click(screen.getByRole("button", { name: "Retry evidence" }))

    // Then
    expect(screen.getByRole("alert")).toHaveTextContent("EVIDENCE_TIMEOUT")
    expect(onRetry).toHaveBeenCalledOnce()
  })

  it("retains ordered event, patch, approval, and evidence semantics", () => {
    // Given
    const events = [
      {
        id: "event-1",
        timestamp: "+00:00:01.234",
        type: "Neighbor discovery converged",
        impacted: "SITE_C",
        severity: "info",
        evidenceId: "ev-demo-01",
      },
    ] as const

    // When
    render(
      <>
        <EventTimeline title="Simulation trace" events={events} />
        <TypedPatchDiff
          path="configs/site-c.yaml"
          schemaVersion="twin.patch.v1"
          state="rejected"
          validationSummary="Policy constraint failed"
          lines={[
            { number: 12, kind: "removal", content: "max_utilization: 85" },
            { number: 12, kind: "addition", content: "max_utilization: 75" },
          ]}
        />
        <ApprovalEvidence
          state="rejected"
          reason="Freshness threshold exceeded"
          steps={[
            { id: "review", label: "Engineer review", state: "complete" },
            { id: "policy", label: "Policy review", state: "rejected" },
          ]}
        />
        <EvidenceRail
          title="Signed evidence"
          state="approved"
          fields={[{ label: "Replay hash", value: "sha256:demo" }]}
        />
      </>,
    )

    // Then
    expect(screen.getByRole("list", { name: "Simulation trace" })).toBeInTheDocument()
    expect(screen.getByText("Removal: max_utilization: 85")).toBeInTheDocument()
    expect(screen.getByText("Addition: max_utilization: 75")).toBeInTheDocument()
    expect(screen.getByRole("list", { name: "Approval review steps" })).toBeInTheDocument()
    expect(screen.getByRole("complementary", { name: "Signed evidence" })).toBeInTheDocument()
  })

  it("pairs a hidden skeleton with a live loading label", () => {
    // Given
    const loadingLabel = "Loading topology"

    // When
    render(<Skeleton variant="topology" label={loadingLabel} />)

    // Then
    expect(screen.getByRole("status")).toHaveTextContent(loadingLabel)
    expect(screen.getByTestId("skeleton-visual")).toHaveAttribute("aria-hidden", "true")
  })
})
