import { useState } from "react"
import { ConsolePage } from "../components/ConsolePage"
import { FailureNotice } from "../components/FailureNotice"
import { SessionContextState } from "../components/SessionContextState"
import { useConsole } from "../console/ConsoleContext"
import { parseBenchmarkForm } from "../console/form-inputs"
import type { BenchmarkResponse } from "../contracts/generated"
import { DataTable, type DataTableColumn } from "../design/primitives/DataTable"
import { StatusChip } from "../design/primitives/StatusChip"

const RESULT_COLUMNS = [
  { id: "seed", header: "Seed", render: (row: BenchmarkResponse) => row.seed },
  { id: "iterations", header: "Iterations", render: (row: BenchmarkResponse) => row.iterations },
  {
    id: "unique",
    header: "Unique trace hashes",
    render: (row: BenchmarkResponse) => row.unique_trace_hashes,
  },
  {
    id: "deterministic",
    header: "Deterministic",
    render: (row: BenchmarkResponse) => (row.deterministic ? "Yes" : "No"),
  },
  { id: "trace", header: "Trace hash", render: (row: BenchmarkResponse) => row.trace_hash },
] satisfies readonly DataTableColumn<BenchmarkResponse>[]

export function BenchmarkLabPage() {
  const { model, actions } = useConsole()
  const [seedInput, setSeedInput] = useState("6701")
  const [iterationsInput, setIterationsInput] = useState("5")
  const submit = (): void => {
    const parsed = parseBenchmarkForm(seedInput, iterationsInput)
    if (!parsed.ok) {
      actions.reportValidation(parsed.issue)
      return
    }
    void actions.runBenchmark(parsed.value)
  }
  return (
    <ConsolePage title="Benchmark lab">
      {model.snapshot.session === undefined ? (
        <SessionContextState />
      ) : (
        <div className="routeStack">
          <FailureNotice />
          <section className="panel formPanel" aria-labelledby="benchmark-heading">
            <div className="panelHeader">
              <div>
                <h2 id="benchmark-heading">Determinism probe</h2>
                <p>
                  The endpoint reports seed, iterations, unique trace count, deterministic status,
                  and one trace hash only. No quality metrics are inferred.
                </p>
              </div>
              <StatusChip tone="demo" label="Synthetic only" />
            </div>
            <form
              className="scenarioForm"
              noValidate
              onSubmit={(event) => {
                event.preventDefault()
                submit()
              }}
            >
              <label>
                Seed
                <input
                  type="number"
                  min={0}
                  step={1}
                  required
                  value={seedInput}
                  onChange={(event) => setSeedInput(event.currentTarget.value)}
                />
              </label>
              <label>
                Iterations
                <input
                  type="number"
                  min={2}
                  max={25}
                  step={1}
                  required
                  value={iterationsInput}
                  onChange={(event) => setIterationsInput(event.currentTarget.value)}
                />
              </label>
              <button className="primaryAction" type="submit" disabled={model.busy !== null}>
                Run determinism probe
              </button>
            </form>
          </section>
          <DataTable
            caption="Verified benchmark response"
            columns={RESULT_COLUMNS}
            rows={model.benchmark ? [model.benchmark] : []}
            rowKey={(row) => `${row.seed}-${row.iterations}`}
            state={model.busy === "benchmark" ? "loading" : model.benchmark ? "default" : "empty"}
          />
        </div>
      )}
    </ConsolePage>
  )
}
