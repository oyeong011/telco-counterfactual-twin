import { Link, useLocation } from "@tanstack/react-router"
import { Activity, FileCheck2, Gauge, Info, Moon, Network, Sun } from "lucide-react"
import { type ReactNode, useEffect } from "react"
import { useConsole } from "../console/ConsoleContext"
import { AppShell } from "../design/primitives/AppShell"
import { CommandBar } from "../design/primitives/CommandBar"
import type { StatusTone } from "../design/primitives/StatusChip"
import { useTheme } from "../design/theme/ThemeProvider"

type ConsolePageProps = {
  readonly title: string
  readonly children: ReactNode
  readonly contextRail?: ReactNode
  readonly evidenceRail?: ReactNode
  readonly actions?: ReactNode
}

function commandStatus(
  phase: ReturnType<typeof useConsole>["model"]["workflow"]["phase"],
  busy: ReturnType<typeof useConsole>["model"]["busy"],
): { readonly tone: StatusTone; readonly label: string; readonly metadata?: string } {
  if (busy !== null) return { tone: "loading", label: "Working", metadata: busy }
  switch (phase) {
    case "no-session":
      return { tone: "neutral", label: "No session" }
    case "session-error":
      return { tone: "danger", label: "Session unavailable" }
    case "approval-blocked":
      return { tone: "warning", label: "Approval blocked" }
    case "decision":
    case "evidence":
      return { tone: "neutral", label: "Evidence recorded" }
    default:
      return { tone: "demo", label: "Synthetic only", metadata: phase }
  }
}

export function ConsolePage({
  title,
  children,
  contextRail,
  evidenceRail,
  actions,
}: ConsolePageProps) {
  const { model } = useConsole()
  const { resolvedTheme, setPreference } = useTheme()
  const location = useLocation()
  useEffect(() => {
    document.title = `${title} · Telco Counterfactual Twin Console`
    document.getElementById("main-content")?.focus()
  }, [title])
  const runId = model.snapshot.run?.runId ?? "current"
  const navigationContent = (
    <>
      <li>
        <Link
          className="primaryNavLink"
          to="/"
          aria-current={location.pathname === "/" ? "page" : undefined}
        >
          <Network aria-hidden="true" />
          <span>Workbench</span>
        </Link>
      </li>
      <li>
        <Link
          className="primaryNavLink"
          to="/runs/$runId"
          params={{ runId }}
          aria-current={location.pathname.startsWith("/runs/") ? "page" : undefined}
        >
          <Activity aria-hidden="true" />
          <span>Run detail</span>
        </Link>
      </li>
      <li>
        <Link
          className="primaryNavLink"
          to="/evidence"
          aria-current={location.pathname === "/evidence" ? "page" : undefined}
        >
          <FileCheck2 aria-hidden="true" />
          <span>Evidence</span>
        </Link>
      </li>
      <li>
        <Link
          className="primaryNavLink"
          to="/benchmarks"
          aria-current={location.pathname === "/benchmarks" ? "page" : undefined}
        >
          <Gauge aria-hidden="true" />
          <span>Benchmarks</span>
        </Link>
      </li>
      <li>
        <Link
          className="primaryNavLink"
          to="/about"
          aria-current={location.pathname === "/about" ? "page" : undefined}
        >
          <Info aria-hidden="true" />
          <span>About</span>
        </Link>
      </li>
    </>
  )
  const ThemeIcon = resolvedTheme === "dark" ? Sun : Moon
  const commandActions = (
    <div className="commandCluster">
      {actions}
      <button
        type="button"
        onClick={() => setPreference(resolvedTheme === "dark" ? "light" : "dark")}
        aria-label={`Use ${resolvedTheme === "dark" ? "light" : "dark"} theme`}
      >
        <ThemeIcon aria-hidden="true" />
        Theme
      </button>
    </div>
  )

  return (
    <AppShell
      navigation={[]}
      navigationContent={navigationContent}
      commandBar={
        <CommandBar
          title={title}
          status={commandStatus(model.workflow.phase, model.busy)}
          actions={commandActions}
          announcement={model.busy ? `${model.busy} in progress` : model.workflow.phase}
        />
      }
      {...(contextRail ? { contextRail } : {})}
      {...(evidenceRail ? { evidenceRail } : {})}
    >
      {children}
    </AppShell>
  )
}
