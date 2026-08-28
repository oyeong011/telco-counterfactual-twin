import { useRouter } from "@tanstack/react-router"
import { ErrorState } from "../design/primitives/ErrorState"

export function SessionContextState() {
  const router = useRouter()
  return (
    <ErrorState
      title="Session context missing"
      code="SESSION_CONTEXT_MISSING"
      detail="This tab has no in-memory session token. Start a new synthetic session from Workbench; stored run identifiers are never opened without their owning token."
      retryLabel="Open Workbench"
      onRetry={() => void router.navigate({ href: "/" })}
    />
  )
}
