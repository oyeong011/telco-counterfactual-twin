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

  it("opens mobile evidence details as a dialog and restores focus after Escape", async () => {
    // Given
    const user = userEvent.setup()
    render(
      <EvidenceRail
        title="Mobile evidence details"
        state="approved"
        fields={[{ label: "Replay hash", value: "sha256:mobile" }]}
      />,
    )
    const trigger = screen.getByRole("button", { name: "Open mobile evidence details" })

    // When
    await user.click(trigger)

    // Then
    const dialog = screen.getByRole("dialog", { name: "Mobile evidence details" })
    expect(dialog).toBeVisible()
    expect(dialog).toHaveAttribute("aria-modal", "true")
    expect(screen.getByRole("button", { name: "Close mobile evidence details" })).toHaveFocus()

    // When
    await user.keyboard("{Escape}")

    // Then
    expect(
      screen.queryByRole("dialog", { name: "Mobile evidence details" }),
    ).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()
  })

  it("generates unique labelled headings for multiple approval evidence instances", () => {
    // Given
    render(
      <>
        <ApprovalEvidence state="rejected" steps={[]} />
        <ApprovalEvidence state="approved" steps={[]} />
      </>,
    )

    // When
    const sections = screen.getAllByRole("region", { name: "Approval evidence" })
    const labelledBy = sections.map((section) => section.getAttribute("aria-labelledby"))

    // Then
    expect(labelledBy).toHaveLength(2)
    expect(new Set(labelledBy).size).toBe(2)
    expect(document.querySelectorAll("#approval-title")).toHaveLength(0)
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

  it("keeps ErrorState text readable when its component container is compact", () => {
    // Given
    render(
      <div style={{ inlineSize: "256px" }}>
        <ErrorState
          title="Evidence unavailable"
          code="EVIDENCE_TIMEOUT"
          detail="The signed package did not arrive."
          requestId="req-demo-17"
          onRetry={() => undefined}
        />
      </div>,
    )

    // When
    const error = screen.getByRole("status")

    // Then
    expect(error).toHaveAttribute("data-layout", "component-aware")
    expect(error.querySelector("h3")).toHaveTextContent("Evidence unavailable")
    expect(error.querySelector("p")).toHaveTextContent("EVIDENCE_TIMEOUT")
  })

  it("exposes evidence recovery and approval decision actions in the primitive gallery", async () => {
    // Given
    const user = userEvent.setup()
    const onCopy = vi.fn()
    const onApprove = vi.fn()
    const onReject = vi.fn()
    render(
      <>
        <EvidenceRail
          title="Evidence actions"
          state="default"
          fields={[{ label: "Replay hash", value: "sha256:actions" }]}
          onCopy={onCopy}
        />
        <ApprovalEvidence
          state="default"
          steps={[{ id: "review", label: "Engineer review", state: "pending" }]}
          onApprove={onApprove}
          onReject={onReject}
        />
      </>,
    )

    // When
    await user.click(screen.getByRole("button", { name: "Copy evidence hash" }))
    await user.click(screen.getByRole("button", { name: "Record approval evidence" }))
    await user.click(screen.getByRole("button", { name: "Record rejection evidence" }))

    // Then
    expect(onCopy).toHaveBeenCalledOnce()
    expect(onApprove).toHaveBeenCalledOnce()
    expect(onReject).toHaveBeenCalledOnce()
  })

  it("blocks approval evidence actions when freshness is stale or synthetic", () => {
    // Given
    render(
      <>
        <ApprovalEvidence
          state="stale"
          steps={[]}
          actionsDisabledReason="Freshness policy blocked this record."
          onApprove={() => undefined}
          onReject={() => undefined}
        />
        <ApprovalEvidence
          state="demo"
          steps={[]}
          actionsDisabledReason="Synthetic demo evidence cannot be approved."
          onApprove={() => undefined}
          onReject={() => undefined}
        />
      </>,
    )

    // When
    const approvalButtons = screen.getAllByRole("button", { name: "Record approval evidence" })
    const rejectionButtons = screen.getAllByRole("button", { name: "Record rejection evidence" })

    // Then
    expect(approvalButtons).toHaveLength(2)
    for (const button of approvalButtons) expect(button).toBeDisabled()
    for (const button of rejectionButtons) expect(button).not.toBeDisabled()
    expect(approvalButtons[0]).toHaveAttribute("title", "Freshness policy blocked this record.")
    expect(approvalButtons[1]).toHaveAttribute(
      "title",
      "Synthetic demo evidence cannot be approved.",
    )
  })
})
