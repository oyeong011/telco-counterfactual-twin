import { ConsolePage } from "../components/ConsolePage"
import { CurrentEvidenceRail, ScenarioRail } from "../components/ConsoleRails"
import { FailureNotice } from "../components/FailureNotice"
import {
  ApprovalPanel,
  ComparisonPanel,
  CurrentEventTimeline,
  LifecycleProgress,
  TopologyContractPanel,
} from "../components/LifecyclePanels"
import { PatchEditor, SubmittedPatchPanel } from "../components/PatchEditor"
import { ScenarioObjectHeader, WorkbenchEntry } from "../components/WorkbenchActions"
import { useConsole } from "../console/ConsoleContext"
import { StatusChip } from "../design/primitives/StatusChip"

export function ScenarioWorkbenchPage() {
  const { model } = useConsole()
  const diagnosis = model.snapshot.diagnosis
  return (
    <ConsolePage
      title="Scenario workbench"
      contextRail={<ScenarioRail />}
      evidenceRail={<CurrentEvidenceRail />}
    >
      <div className="routeStack">
        <FailureNotice />
        <WorkbenchEntry />
        <ScenarioObjectHeader />
        {model.snapshot.session ? <LifecycleProgress /> : null}
        {model.snapshot.scenario ? (
          <div className="workbenchGrid">
            <TopologyContractPanel />
            <section className="panel diagnosisPanel" aria-labelledby="diagnosis-heading">
              <div className="panelHeader">
                <h2 id="diagnosis-heading">Diagnosis</h2>
                <StatusChip
                  tone={diagnosis ? "info" : "neutral"}
                  label={diagnosis?.status ?? "Not requested"}
                />
              </div>
              {diagnosis ? (
                <dl className="evidenceFields">
                  <div>
                    <dt>Primary fault</dt>
                    <dd>{diagnosis.primary_fault ?? "No primary fault"}</dd>
                  </div>
                  <div>
                    <dt>Secondary evidence</dt>
                    <dd>{diagnosis.secondary_evidence.join(", ") || "None returned"}</dd>
                  </div>
                </dl>
              ) : (
                <p className="emptyMessage">Run the contract diagnosis before drafting a patch.</p>
              )}
            </section>
          </div>
        ) : null}
        {model.workflow.phase === "diagnosis" ? <PatchEditor /> : null}
        <SubmittedPatchPanel />
        {model.snapshot.comparison ? <ComparisonPanel /> : null}
        <ApprovalPanel />
        {model.snapshot.run ? <CurrentEventTimeline /> : null}
      </div>
    </ConsolePage>
  )
}
