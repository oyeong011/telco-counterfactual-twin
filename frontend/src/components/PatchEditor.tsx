import { useState } from "react"
import { useConsole } from "../console/ConsoleContext"
import { buildTypedPatch, defaultPatchInput, type PatchEditorInput } from "../console/patch-builder"
import {
  PatchOperationSchema,
  PatchOperationValues,
  TargetKindSchema,
  TargetKindValues,
  type TypedPatch,
} from "../contracts/generated"
import { type PatchLine, TypedPatchDiff } from "../design/primitives/TypedPatchDiff"

export function PatchEditor() {
  const { model, actions } = useConsole()
  const scenario = model.snapshot.scenario
  if (scenario === undefined) return null
  return (
    <PatchEditorForm
      scenario={scenario}
      busy={model.busy === "patch"}
      onSubmit={actions.proposePatch}
      onInvalid={actions.reportValidation}
    />
  )
}

type PatchEditorFormProps = {
  readonly scenario: NonNullable<ReturnType<typeof useConsole>["model"]["snapshot"]["scenario"]>
  readonly busy: boolean
  readonly onSubmit: (patch: TypedPatch) => Promise<void>
  readonly onInvalid: (issue: string) => void
}

function PatchEditorForm({ scenario, busy, onSubmit, onInvalid }: PatchEditorFormProps) {
  const [input, setInput] = useState<PatchEditorInput>(() => defaultPatchInput(scenario))
  const update = (change: Partial<PatchEditorInput>): void =>
    setInput((current) => ({ ...current, ...change }))
  const submit = (): void => {
    const result = buildTypedPatch(scenario, input)
    if (!result.ok) {
      onInvalid(result.issue)
      return
    }
    void onSubmit(result.patch)
  }

  return (
    <section className="panel formPanel" aria-labelledby="patch-editor-heading">
      <div className="panelHeader">
        <div>
          <h2 id="patch-editor-heading">Typed patch editor</h2>
          <p>Only the exact validated payload below is submitted and retained for this tab.</p>
        </div>
      </div>
      <form
        className="patchEditorGrid"
        onSubmit={(event) => {
          event.preventDefault()
          submit()
        }}
      >
        <label>
          Patch ID
          <input
            value={input.patchId}
            onChange={(event) => update({ patchId: event.currentTarget.value })}
          />
        </label>
        <label>
          Target ID
          <input
            value={input.targetId}
            onChange={(event) => update({ targetId: event.currentTarget.value })}
          />
        </label>
        <label>
          Target kind
          <select
            value={input.targetKind}
            onChange={(event) => {
              const parsed = TargetKindSchema.safeParse(event.currentTarget.value)
              if (parsed.success) update({ targetKind: parsed.data })
            }}
          >
            {TargetKindValues.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>
        <label>
          Operation
          <select
            value={input.operation}
            onChange={(event) => {
              const parsed = PatchOperationSchema.safeParse(event.currentTarget.value)
              if (parsed.success) update({ operation: parsed.data })
            }}
          >
            {PatchOperationValues.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>
        <label className="formSpan">
          Patch parameters (JSON)
          <textarea
            rows={5}
            value={input.parametersJson}
            onChange={(event) => update({ parametersJson: event.currentTarget.value })}
            spellCheck={false}
          />
        </label>
        <label>
          Maximum cells
          <input
            type="number"
            min={0}
            max={4}
            value={input.maxCells}
            onChange={(event) => update({ maxCells: event.currentTarget.valueAsNumber })}
          />
        </label>
        <label>
          Maximum UE cohorts
          <input
            type="number"
            min={0}
            max={32}
            value={input.maxUeCohorts}
            onChange={(event) => update({ maxUeCohorts: event.currentTarget.valueAsNumber })}
          />
        </label>
        <label>
          Maximum slices
          <input
            type="number"
            min={0}
            max={8}
            value={input.maxSlices}
            onChange={(event) => update({ maxSlices: event.currentTarget.valueAsNumber })}
          />
        </label>
        <label>
          Proposed at (UTC)
          <input value={input.proposedAt} readOnly />
        </label>
        <button className="primaryAction formSpan" type="submit" disabled={busy}>
          Validate and propose patch
        </button>
      </form>
    </section>
  )
}

function patchLines(patch: TypedPatch): readonly PatchLine[] {
  return JSON.stringify(patch, null, 2)
    .split("\n")
    .map((content, index) => ({
      id: `patch-line-${index + 1}`,
      number: index + 1,
      kind: "context",
      content,
    }))
}

export function SubmittedPatchPanel() {
  const { model } = useConsole()
  const patch = model.snapshot.run?.patchBody
  if (patch === undefined) return null
  const serialized = JSON.stringify(patch, null, 2)
  return (
    <div className="submittedPatchStack">
      <section className="panel blastRadiusPanel" aria-labelledby="blast-radius-heading">
        <div className="panelHeader">
          <h2 id="blast-radius-heading">Blast radius</h2>
        </div>
        <dl className="objectFacts">
          <div>
            <dt>Maximum cells</dt>
            <dd>{patch.blast_radius.max_cells}</dd>
          </div>
          <div>
            <dt>Maximum UE cohorts</dt>
            <dd>{patch.blast_radius.max_ue_cohorts}</dd>
          </div>
          <div>
            <dt>Maximum slices</dt>
            <dd>{patch.blast_radius.max_slices}</dd>
          </div>
        </dl>
      </section>
      <TypedPatchDiff
        path={patch.patch_id}
        schemaVersion={patch.schema_version}
        validationSummary="Accepted by the typed HTTP contract. This is the exact submitted payload."
        lines={patchLines(patch)}
        onCopy={() => void navigator.clipboard.writeText(serialized)}
      />
      <details className="rawPayload">
        <summary>Exact submitted JSON</summary>
        <pre>{serialized}</pre>
      </details>
    </div>
  )
}
