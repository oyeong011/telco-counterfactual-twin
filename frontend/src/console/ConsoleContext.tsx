import { createContext, type ReactNode, useContext, useMemo, useState } from "react"
import { type ApiClient, createApiClient } from "../api/client"
import { ContractParseError } from "../api/errors"
import type { BenchmarkRequest, ScenarioCreateRequest, TypedPatch } from "../contracts/generated"
import { ConsoleRuntime } from "./ConsoleRuntime"
import type { ConsoleModel, ConsoleOperation } from "./console-model"

export type ConsoleActions = {
  readonly bootstrap: () => Promise<void>
  readonly resetSession: () => void
  readonly refreshScenarios: () => Promise<void>
  readonly createScenario: (input: ScenarioCreateRequest) => Promise<void>
  readonly diagnose: () => Promise<void>
  readonly proposePatch: (patch: TypedPatch) => Promise<void>
  readonly simulate: () => Promise<void>
  readonly compare: () => Promise<void>
  readonly requestApproval: () => Promise<void>
  readonly decide: (decision: "approve" | "reject") => Promise<void>
  readonly loadEvidence: () => Promise<void>
  readonly replayEvents: () => Promise<void>
  readonly runBenchmark: (input: BenchmarkRequest) => Promise<void>
  readonly reportValidation: (issue: string) => void
}

type ConsoleContextValue = {
  readonly model: ConsoleModel
  readonly actions: ConsoleActions
}

const ConsoleContext = createContext<ConsoleContextValue | null>(null)

type ConsoleProviderProps = {
  readonly client?: ApiClient
  readonly children: ReactNode
}

export function ConsoleProvider({ client, children }: ConsoleProviderProps) {
  const [runtime] = useState(() => new ConsoleRuntime(client ?? createApiClient()))
  const [model, setModel] = useState(() => runtime.getModel())
  const actions = useMemo<ConsoleActions>(() => {
    const sync = (): void => setModel(runtime.getModel())
    const perform = async (
      operation: ConsoleOperation,
      task: () => Promise<void>,
    ): Promise<void> => {
      runtime.clearTransient()
      runtime.setBusy(operation)
      sync()
      try {
        await task()
      } catch (error) {
        if (error instanceof ContractParseError) runtime.recordContractFailure()
        else throw error
      } finally {
        runtime.setBusy(null)
        sync()
      }
    }
    return {
      bootstrap: () => perform("bootstrap", () => runtime.bootstrap()),
      resetSession: () => {
        runtime.reset()
        sync()
      },
      refreshScenarios: () => perform("scenario", () => runtime.refreshScenarios()),
      createScenario: (input) => perform("scenario", () => runtime.createScenario(input)),
      diagnose: () => perform("diagnosis", () => runtime.diagnose()),
      proposePatch: (patch) => perform("patch", () => runtime.proposePatch(patch)),
      simulate: () => perform("simulation", () => runtime.simulate()),
      compare: () => perform("comparison", () => runtime.compare()),
      requestApproval: () => perform("approval", () => runtime.requestApproval()),
      decide: (decision) => perform("decision", () => runtime.decide(decision)),
      loadEvidence: () => perform("evidence", () => runtime.loadEvidence()),
      replayEvents: () => perform("events", () => runtime.replayEvents()),
      runBenchmark: (input) => perform("benchmark", () => runtime.runBenchmark(input)),
      reportValidation: (issue) => {
        runtime.setValidationIssue(issue)
        sync()
      },
    }
  }, [runtime])
  const value = useMemo(() => ({ model, actions }), [model, actions])

  return <ConsoleContext.Provider value={value}>{children}</ConsoleContext.Provider>
}

export function useConsole(): ConsoleContextValue {
  const context = useContext(ConsoleContext)
  if (context === null) throw new TypeError("useConsole must be used inside ConsoleProvider")
  return context
}
