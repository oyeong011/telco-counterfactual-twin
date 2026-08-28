import { Download } from "lucide-react"
import { ConsolePage } from "../components/ConsolePage"
import { CurrentEvidenceRail, ScenarioRail } from "../components/ConsoleRails"
import { FailureNotice } from "../components/FailureNotice"
import { SessionContextState } from "../components/SessionContextState"
import { useConsole } from "../console/ConsoleContext"
import { downloadEvidenceJson } from "../console/evidence-download"
import type { Event } from "../contracts/generated"
import { DataTable, type DataTableColumn } from "../design/primitives/DataTable"
import { StatusChip } from "../design/primitives/StatusChip"

const EVENT_COLUMNS = [
  { id: "sequence", header: "Sequence", render: (event: Event) => event.sequence_id },
  { id: "time", header: "Timestamp", render: (event: Event) => event.timestamp },
  { id: "type", header: "Event", render: (event: Event) => event.event_type },
  { id: "evidence", header: "Evidence ID", render: (event: Event) => event.event_id },
] satisfies readonly DataTableColumn<Event>[]

export function EvidenceBoardPage() {
  const { model, actions } = useConsole()
  const evidence = model.snapshot.evidence
  return (
    <ConsolePage
      title="Evidence board"
      contextRail={<ScenarioRail />}
      evidenceRail={<CurrentEvidenceRail />}
    >
      {model.snapshot.session === undefined ? (
        <SessionContextState />
      ) : (
        <div className="routeStack">
          <FailureNotice />
          <section className="panel evidenceBoardHeader" aria-labelledby="evidence-board-heading">
            <div>
              <h2 id="evidence-board-heading">
                {evidence ? "Evidence package verified" : "No evidence package loaded"}
              </h2>
              <p>
                Export contains only the parsed backend evidence response. Approval remains
                evidence-only.
              </p>
            </div>
            {evidence ? (
              <button type="button" onClick={() => downloadEvidenceJson(evidence)}>
                <Download aria-hidden="true" />
                Download evidence JSON
              </button>
            ) : model.workflow.phase === "decision" ? (
              <button
                type="button"
                disabled={model.busy !== null}
                onClick={() => void actions.loadEvidence()}
              >
                Load evidence package
              </button>
            ) : (
              <StatusChip tone="neutral" label="Complete a decision first" />
            )}
          </section>
          <DataTable
            caption="Evidence event ledger"
            columns={EVENT_COLUMNS}
            rows={evidence?.events ?? []}
            rowKey={(event) => event.event_id}
            state={evidence ? "default" : "empty"}
          />
        </div>
      )}
    </ConsolePage>
  )
}
