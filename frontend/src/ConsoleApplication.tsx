import { RouterProvider } from "@tanstack/react-router"
import { useMemo } from "react"
import type { ApiClient } from "./api/client"
import { ConsoleProvider } from "./console/ConsoleContext"
import { ThemeProvider } from "./design/theme/ThemeProvider"
import { type ConsoleHistory, createConsoleRouter } from "./router"

type ConsoleApplicationProps = {
  readonly client?: ApiClient
  readonly history?: ConsoleHistory
}

export function ConsoleApplication({ client, history }: ConsoleApplicationProps) {
  const router = useMemo(() => createConsoleRouter(history), [history])
  return (
    <ThemeProvider>
      <ConsoleProvider {...(client ? { client } : {})}>
        <RouterProvider router={router} />
      </ConsoleProvider>
    </ThemeProvider>
  )
}
