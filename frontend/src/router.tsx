import {
  type createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  Outlet,
} from "@tanstack/react-router"
import { loadUiBuildInfo } from "./console/build-info"
import { ErrorState } from "./design/primitives/ErrorState"
import { AboutPage } from "./pages/AboutPage"
import { BenchmarkLabPage } from "./pages/BenchmarkLabPage"
import { EvidenceBoardPage } from "./pages/EvidenceBoardPage"
import { RunDetailPage } from "./pages/RunDetailPage"
import { ScenarioWorkbenchPage } from "./pages/ScenarioWorkbenchPage"

const rootRoute = createRootRoute({
  component: Outlet,
  notFoundComponent: () => (
    <main className="notFoundPage">
      <ErrorState
        title="Route not found"
        code="route_not_found"
        detail="Open Workbench, Evidence, Benchmarks, or About from the product navigation."
      />
    </main>
  ),
})

const workbenchRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  component: ScenarioWorkbenchPage,
})
const runRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/runs/$runId",
  component: () => {
    const { runId } = runRoute.useParams()
    return <RunDetailPage runId={runId} />
  },
})
const evidenceRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/evidence",
  component: EvidenceBoardPage,
})
const benchmarkRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/benchmarks",
  component: BenchmarkLabPage,
})
const aboutRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/about",
  loader: loadUiBuildInfo,
  component: () => <AboutPage buildInfo={aboutRoute.useLoaderData()} />,
})

const routeTree = rootRoute.addChildren([
  workbenchRoute,
  runRoute,
  evidenceRoute,
  benchmarkRoute,
  aboutRoute,
])

export type ConsoleHistory = ReturnType<typeof createMemoryHistory>

export function createConsoleRouter(history?: ConsoleHistory) {
  return createRouter({ routeTree, ...(history ? { history } : {}) })
}
