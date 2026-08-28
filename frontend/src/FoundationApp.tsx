import { FileLock2 } from "lucide-react"
import { StatusChip } from "./design/primitives/StatusChip"

export function FoundationApp() {
  return (
    <main className="foundationRoot">
      <FileLock2 aria-hidden="true" />
      <StatusChip tone="neutral" label="Foundation build" />
      <h1>Console foundation</h1>
      <p>Product routes are intentionally excluded from this build.</p>
    </main>
  )
}
