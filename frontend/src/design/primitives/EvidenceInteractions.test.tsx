import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { useState } from "react"
import { describe, expect, it } from "vitest"
import { type ApprovalDecision, ApprovalEvidence } from "./ApprovalEvidence"
import { EvidenceRail } from "./EvidenceRail"

function EvidenceHarness() {
  const [selectedArtifactId, setSelectedArtifactId] = useState("replay")
  const [selectedAction, setSelectedAction] = useState<"copy">()
  return (
    <EvidenceRail
      title="Evidence package"
      fields={[
        { id: "replay", label: "Replay hash", value: "sha256:fixture" },
        { id: "scenario", label: "Scenario", value: "CF-DEMO-RUN-024" },
      ]}
      selectedArtifactId={selectedArtifactId}
      {...(selectedAction ? { selectedAction } : {})}
      onSelectArtifact={setSelectedArtifactId}
      onCopy={() => setSelectedAction("copy")}
    />
  )
}

function ApprovalHarness() {
  const [decision, setDecision] = useState<ApprovalDecision>("pending")
  return (
    <ApprovalEvidence
      state="default"
      decision={decision}
      steps={[{ id: "review", label: "Engineer review", state: "pending" }]}
      onApprove={() => setDecision("approved")}
      onReject={() => setDecision("rejected")}
    />
  )
}

describe("interactive evidence primitives", () => {
  it("selects an evidence artifact and records its action", async () => {
    // Given
    const user = userEvent.setup()
    render(<EvidenceHarness />)
    const scenario = screen.getByRole("button", { name: "Select Scenario" })
    const copy = screen.getByRole("button", { name: "Copy evidence hash" })

    // When
    await user.click(scenario)

    // Then
    expect(scenario).toHaveAttribute("aria-pressed", "true")
    expect(scenario).toHaveFocus()

    // When
    await user.click(copy)

    // Then
    expect(copy).toHaveAttribute("aria-pressed", "true")
  })

  it("exposes the controlled approval decision on its real actions", async () => {
    // Given
    const user = userEvent.setup()
    render(<ApprovalHarness />)
    const approve = screen.getByRole("button", { name: "Record approval evidence" })
    const reject = screen.getByRole("button", { name: "Record rejection evidence" })

    // When
    await user.click(approve)

    // Then
    expect(approve).toHaveAttribute("aria-pressed", "true")
    expect(reject).toHaveAttribute("aria-pressed", "false")
    expect(approve).toHaveFocus()

    // When
    await user.click(reject)

    // Then
    expect(approve).toHaveAttribute("aria-pressed", "false")
    expect(reject).toHaveAttribute("aria-pressed", "true")
  })
})
