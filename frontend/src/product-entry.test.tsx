import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { ConsoleApplication } from "./ConsoleApplication"

describe("product console entry", () => {
  it("exposes the five governed product routes instead of the foundation placeholder", async () => {
    render(<ConsoleApplication />)

    expect(await screen.findByRole("link", { name: "Workbench" })).toHaveAttribute("href", "/")
    expect(screen.getByRole("link", { name: "Run detail" })).toHaveAttribute(
      "href",
      "/runs/current",
    )
    expect(screen.getByRole("link", { name: "Evidence" })).toHaveAttribute("href", "/evidence")
    expect(screen.getByRole("link", { name: "Benchmarks" })).toHaveAttribute("href", "/benchmarks")
    expect(screen.getByRole("link", { name: "About" })).toHaveAttribute("href", "/about")
    expect(screen.queryByText("Console foundation")).not.toBeInTheDocument()
  })
})
