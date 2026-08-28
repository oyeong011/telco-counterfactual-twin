import { defineConfig } from "@playwright/test"

// biome-ignore lint/style/noDefaultExport: Playwright requires the config as a default export.
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  reporter: "line",
  use: {
    baseURL: "http://localhost:4173",
    channel: "chrome",
    headless: true,
    trace: "retain-on-failure",
  },
  webServer: [
    {
      command:
        "uv run --project ../backend uvicorn telco_twin.api.app:app --app-dir ../backend/src --host 127.0.0.1 --port 18080",
      url: "http://127.0.0.1:18080/healthz",
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command:
        "VITE_API_BASE_URL=http://127.0.0.1:18080 VITE_DISABLE_REACT_DEVTOOLS=1 node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 4173 --strictPort",
      url: "http://localhost:4173/__showcase",
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
})
