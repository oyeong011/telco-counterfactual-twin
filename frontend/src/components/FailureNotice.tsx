import { useConsole } from "../console/ConsoleContext"
import { ErrorState } from "../design/primitives/ErrorState"

export function FailureNotice() {
  const { model } = useConsole()
  if (model.failure === null && model.validationIssue === null) return null
  if (model.failure === null)
    return (
      <ErrorState
        title="Client validation stopped the request"
        code="CLIENT_VALIDATION"
        detail={model.validationIssue ?? "The input did not satisfy the client contract."}
      />
    )
  const policyGap =
    model.failure.problem.code === "policy_ineligible"
      ? " The current HTTP error does not return policy reasons, so the console cannot truthfully attribute the block to stale telemetry or another cause."
      : ""
  return (
    <ErrorState
      title={model.failure.problem.title}
      code={model.failure.problem.code}
      detail={`${model.failure.problem.detail}${policyGap}`}
      requestId={model.failure.requestId}
      blocking={model.workflow.phase === "session-error"}
    />
  )
}
