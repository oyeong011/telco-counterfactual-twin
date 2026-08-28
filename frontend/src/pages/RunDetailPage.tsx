import { ConsolePage } from "../components/ConsolePage"
import { CurrentEvidenceRail, ScenarioRail } from "../components/ConsoleRails"
import { FailureNotice } from "../components/FailureNotice"
import {
  ApprovalPanel,
  ComparisonPanel,
  CurrentEventTimeline,
  TopologyContractPanel,
} from "../components/LifecyclePanels"
import { SubmittedPatchPanel } from "../components/PatchEditor"
import { SessionContextState } from "../components/SessionContextState"
import { useConsole } from "../console/ConsoleContext"
import { ErrorState } from "../design/primitives/ErrorState"

type RunDetailPageProps = {
  readonly runId: string
}

export function RunDetailPage({ runId }: RunDetailPageProps) {
  const { model } = useConsole()
  const run = model.snapshot.run
  const content =
    model.snapshot.session === undefined ? (
      <SessionContextState />
    ) : run === undefined || run.runId !== runId ? (
      <ErrorState
        title="Run unavailable in this tab"
        code="run_not_found"
        detail="The backend has no run aggregate read endpoint. Open a run created by the current in-memory session from Workbench."
      />
    ) : (
      <div className="routeStack">
        <FailureNotice />
        <header className="objectHeader">
          <div>
            <p className="objectEyebrow">Run detail</p>
            <h2 className="mono">{run.runId}</h2>
          </div>
          <dl className="objectFacts">
            <div>
              <dt>Scenario</dt>
              <dd className="mono">{run.scenarioId}</dd>
            </div>
            <div>
              <dt>Patch</dt>
              <dd className="mono">{run.patchId ?? "Not proposed"}</dd>
            </div>
            <div>
              <dt>Simulation</dt>
              <dd className="mono">{run.simulationId ?? "Not created"}</dd>
            </div>
          </dl>
        </header>
        <TopologyContractPanel />
        <CurrentEventTimeline />
        <ComparisonPanel />
        <SubmittedPatchPanel />
        <ApprovalPanel />
      </div>
    )
  return (
    <ConsolePage
      title="Run detail"
      contextRail={<ScenarioRail />}
      evidenceRail={<CurrentEvidenceRail />}
    >
      {content}
    </ConsolePage>
  )
}
