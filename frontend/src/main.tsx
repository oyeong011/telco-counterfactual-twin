import "@fontsource-variable/rubik"
import "@fontsource/ibm-plex-mono/400.css"
import "@fontsource/ibm-plex-mono/500.css"
import { type ReactNode, StrictMode } from "react"
import { createRoot } from "react-dom/client"
import { ThemeProvider } from "./design/theme/ThemeProvider"
import { FoundationApp } from "./FoundationApp"
import { shouldRenderShowcase } from "./showcase/showcaseGate"
import "./styles/tokens.css"
import "./styles/base.css"
import "./styles/shell.css"
import "./styles/states.css"
import "./styles/data.css"
import "./styles/evidence.css"

const rootElement = document.getElementById("root")
if (rootElement === null) {
  throw new TypeError("Application root is missing")
}

const root = createRoot(rootElement)
const render = (application: ReactNode) => {
  root.render(
    <StrictMode>
      <ThemeProvider>{application}</ThemeProvider>
    </StrictMode>,
  )
}

const reactDevToolsEnabled =
  import.meta.env.DEV && import.meta.env.VITE_DISABLE_REACT_DEVTOOLS !== "1"

if (reactDevToolsEnabled) {
  void import("react-grab")
  void import("react-scan")
}

const renderFoundation = () => render(<FoundationApp />)

if (import.meta.env.DEV) {
  if (
    shouldRenderShowcase({
      isDevelopment: import.meta.env.DEV,
      pathname: window.location.pathname,
    })
  ) {
    void import("./showcase/PrimitiveShowcase").then(({ PrimitiveShowcase }) => {
      render(<PrimitiveShowcase />)
    })
  } else {
    renderFoundation()
  }
} else {
  renderFoundation()
}
