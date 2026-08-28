import { ConsolePage } from "../components/ConsolePage"
import type { BuildInfoState } from "../console/build-info"
import type { UiBuildInfo } from "../contracts/generated"
import { DataTable, type DataTableColumn } from "../design/primitives/DataTable"
import { StatusChip } from "../design/primitives/StatusChip"

type BuildRow = { readonly label: string; readonly value: string }
const BUILD_COLUMNS = [
  { id: "field", header: "Build field", render: (row: BuildRow) => row.label },
  { id: "value", header: "Parsed value", render: (row: BuildRow) => row.value },
] satisfies readonly DataTableColumn<BuildRow>[]

function rowsFor(info: UiBuildInfo): readonly BuildRow[] {
  return [
    { label: "Service", value: info.service_name },
    { label: "Version", value: info.version },
    { label: "Runtime source commit", value: info.runtime_source_commit_sha },
    { label: "Release commit", value: info.release_commit_sha },
    { label: "Runtime tree hash", value: info.runtime_tree_hash },
    { label: "Asset manifest hash", value: info.asset_manifest_hash },
    { label: "Built at", value: info.built_at },
  ]
}

type AboutPageProps = { readonly buildInfo: BuildInfoState }

export function AboutPage({ buildInfo }: AboutPageProps) {
  const rows = buildInfo.kind === "available" ? rowsFor(buildInfo.value) : []
  return (
    <ConsolePage title="System boundaries">
      <div className="aboutLayout">
        <section className="aboutIntro" aria-labelledby="about-heading">
          <StatusChip tone="neutral" label="Evidence, never execution" />
          <h2 id="about-heading">System boundaries</h2>
          <p>
            This portfolio console creates synthetic scenarios, records deterministic comparisons,
            and receives backend-issued evidence-only approval decisions. It has no mutation
            authority over a network.
          </p>
        </section>
        <section className="panel limitationsPanel" aria-labelledby="limitations-heading">
          <div className="panelHeader">
            <h2 id="limitations-heading">Precise limitations</h2>
          </div>
          <ul>
            <li>The demo token is process-memory and tab-memory only.</li>
            <li>The API has no recoverable run aggregate or patch read endpoint.</li>
            <li>The HTTP contract does not expose physical topology nodes or links.</li>
            <li>Policy-ineligible errors do not include structured reasons.</li>
            <li>SSE is a finite replay snapshot, not a live tail.</li>
            <li>
              Certificate and proof signatures are backend-issued data; this browser does not verify
              Ed25519 signatures.
            </li>
          </ul>
        </section>
        {buildInfo.kind === "unavailable" ? (
          <p className="contractGap">{buildInfo.detail}</p>
        ) : null}
        <DataTable
          caption="Frontend build identity from /build-info.json"
          columns={BUILD_COLUMNS}
          rows={rows}
          rowKey={(row) => row.label}
          state={rows.length === 0 ? "empty" : "default"}
        />
      </div>
    </ConsolePage>
  )
}
