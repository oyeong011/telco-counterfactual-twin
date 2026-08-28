import { useState } from "react"
import { useConsole } from "../console/ConsoleContext"
import { parseScenarioForm } from "../console/form-inputs"
import { FaultFamilySchema, FaultFamilyValues } from "../contracts/generated"
import { StatusChip } from "../design/primitives/StatusChip"

export function WorkbenchEntry() {
  const { model, actions } = useConsole()
  switch (model.workflow.phase) {
    case "no-session":
      return (
        <section className="entryPanel" aria-labelledby="session-start-heading">
          <StatusChip tone="demo" label="Synthetic only" />
          <h2 id="session-start-heading">Start an isolated evidence session</h2>
          <p>
            The opaque token stays in memory. Refreshing or opening a deep link intentionally loses
            session authority.
          </p>
          <button
            className="primaryAction"
            type="button"
            disabled={model.busy !== null}
            onClick={() => void actions.bootstrap()}
          >
            Start synthetic session
          </button>
        </section>
      )
    case "bootstrapping":
      return <p role="status">Creating an in-memory synthetic session.</p>
    case "session-error":
      return (
        <section className="entryPanel">
          <h2>Session cannot continue</h2>
          <p>Reset the tab context before requesting a new isolated session.</p>
          <button type="button" disabled={model.busy !== null} onClick={actions.resetSession}>
            Reset session context
          </button>
        </section>
      )
    case "session-active":
      return <ScenarioCreatePanel />
    default:
      return <LifecycleAction />
  }
}

function ScenarioCreatePanel() {
  const { model, actions } = useConsole()
  const [faultFamily, setFaultFamily] = useState("radio-congestion")
  const [seedInput, setSeedInput] = useState("6701")
  const submit = (): void => {
    const parsed = parseScenarioForm(faultFamily, seedInput)
    if (!parsed.ok) {
      actions.reportValidation(parsed.issue)
      return
    }
    void actions.createScenario(parsed.value)
  }
  return (
    <section className="panel formPanel" aria-labelledby="scenario-create-heading">
      <div className="panelHeader">
        <div>
          <h2 id="scenario-create-heading">Create a contract-backed scenario</h2>
          <p>A fresh HTTP session has no predefined scenario catalog.</p>
        </div>
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
          Fault family
          <select
            value={faultFamily}
            onChange={(event) => {
              const value = event.currentTarget.value
              const parsed = FaultFamilySchema.safeParse(value)
              if (parsed.success) setFaultFamily(parsed.data)
            }}
          >
            {FaultFamilyValues.map((fault) => (
              <option key={fault} value={fault}>
                {fault}
              </option>
            ))}
          </select>
        </label>
        <label>
          Deterministic seed
          <input
            type="number"
            min={0}
            step={1}
            required
            value={seedInput}
            onChange={(event) => setSeedInput(event.currentTarget.value)}
          />
        </label>
        <button className="primaryAction" type="submit" disabled={model.busy !== null}>
          Create scenario
        </button>
      </form>
    </section>
  )
}

function LifecycleAction() {
  const { model, actions } = useConsole()
  const phase = model.workflow.phase
  if (phase === "scenario")
    return (
      <button
        className="primaryAction"
        type="button"
        disabled={model.busy !== null}
        onClick={() => void actions.diagnose()}
      >
        Diagnose scenario
      </button>
    )
  if (phase === "patch")
    return (
      <button
        className="primaryAction"
        type="button"
        disabled={model.busy !== null}
        onClick={() => void actions.simulate()}
      >
        Simulate candidate
      </button>
    )
  if (phase === "simulation")
    return (
      <button
        className="primaryAction"
        type="button"
        disabled={model.busy !== null}
        onClick={() => void actions.compare()}
      >
        Compare evidence
      </button>
    )
  if (phase === "comparison")
    return (
      <button
        className="primaryAction"
        type="button"
        disabled={model.busy !== null}
        onClick={() => void actions.requestApproval()}
      >
        Request approval evidence
      </button>
    )
  if (phase === "decision")
    return (
      <button
        className="primaryAction"
        type="button"
        disabled={model.busy !== null}
        onClick={() => void actions.loadEvidence()}
      >
        Load evidence package
      </button>
    )
  if (phase === "evidence") return <StatusChip tone="proof" label="Evidence package verified" />
  return null
}

export function ScenarioObjectHeader() {
  const { model } = useConsole()
  const scenario = model.snapshot.scenario
  if (scenario === undefined) return null
  return (
    <header className="objectHeader">
      <div>
        <p className="objectEyebrow">Scenario object</p>
        <h2>{scenario.scenario.fault_family}</h2>
      </div>
      <dl className="objectFacts">
        <div>
          <dt>Run</dt>
          <dd className="mono">{scenario.run_id}</dd>
        </div>
        <div>
          <dt>Seed</dt>
          <dd className="mono">{scenario.scenario.seed}</dd>
        </div>
        <div>
          <dt>Topology</dt>
          <dd className="mono">{scenario.scenario.topology_id}</dd>
        </div>
        <div>
          <dt>Duration</dt>
          <dd>{scenario.scenario.duration_seconds} seconds</dd>
        </div>
      </dl>
    </header>
  )
}
