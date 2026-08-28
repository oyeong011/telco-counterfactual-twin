import { defineConfig } from "@playwright/test"

// biome-ignore lint/style/noDefaultExport: Playwright requires the config as a default export.
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  reporter: "line",
  use: {
    baseURL: "http://127.0.0.1:4173",
    channel: "chrome",
    headless: true,
    trace: "retain-on-failure",
  },
  webServer: {
    command: "VITE_DISABLE_REACT_DEVTOOLS=1 pnpm dev --host 127.0.0.1 --port 4173 --strictPort",
    url: "http://127.0.0.1:4173/__showcase",
    reuseExistingServer: false,
    timeout: 120_000,
  },
})
