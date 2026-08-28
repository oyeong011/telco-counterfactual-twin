import { createMemoryHistory } from "@tanstack/react-router"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { ConsoleApplication } from "./ConsoleApplication"
import { createConsoleApiFixture } from "./test/consoleApi"

const UI_BUILD_INFO = {
  schema_version: "1.0",
  service_name: "telco-twin-ui",
  version: "0.1.0",
  runtime_source_commit_sha: "a".repeat(40),
  release_commit_sha: "b".repeat(40),
  runtime_tree_hash: "1".repeat(64),
  schema_hashes: { ui: "2".repeat(64) },
  mcp_hash: "3".repeat(64),
  policy_hash: "4".repeat(64),
  trusted_root_hashes: "5".repeat(64),
  built_at: "2026-08-29T00:00:00Z",
  asset_manifest_hash: "6".repeat(64),
}

beforeEach(() => sessionStorage.clear())

describe("artifact-backed secondary routes", () => {
  it("shows only the schema-validated static UI build identity", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          new Response(JSON.stringify(UI_BUILD_INFO), {
            status: 200,
            headers: { "content-type": "application/json" },
          }),
        ),
      ),
    )
    const history = createMemoryHistory({ initialEntries: ["/about"] })
    render(<ConsoleApplication client={createConsoleApiFixture().client} history={history} />)

    expect(await screen.findByText("Release commit")).toBeVisible()
    expect(screen.getByText("b".repeat(40))).toBeVisible()
    expect(screen.getByText("SSE is a finite replay snapshot, not a live tail.")).toBeVisible()
  })

  it("runs the server determinism probe without inventing model quality metrics", async () => {
    const history = createMemoryHistory({ initialEntries: ["/"] })
    render(<ConsoleApplication client={createConsoleApiFixture().client} history={history} />)
    const user = userEvent.setup()
    await user.click(await screen.findByRole("button", { name: "Start synthetic session" }))
    await user.click(screen.getByRole("link", { name: "Benchmarks" }))
    await user.click(await screen.findByRole("button", { name: "Run determinism probe" }))

    expect(await screen.findByText("Verified benchmark response")).toBeVisible()
    expect(screen.getByRole("cell", { name: "Yes" })).toBeVisible()
    expect(screen.getByRole("cell", { name: "1" })).toBeVisible()
    expect(screen.queryByText(/accuracy|quality score|latency percentile/i)).not.toBeInTheDocument()
  })
})
