// End-to-end tests: a REAL Chromium clicks through the REAL dashboard, talking through
// the Next.js proxy to the REAL backend (with a scripted LLM). Run with:  npm run e2e
// Playwright starts both servers itself (webServer below) and stops them afterwards.
import { existsSync } from "node:fs";

import { defineConfig, devices } from "@playwright/test";

const API_PORT = 8020;
const WEB_PORT = 3020;

// The project's virtualenv Python (Windows or Linux layout), or E2E_PYTHON (CI).
const PYTHON = process.env.E2E_PYTHON
  || ["../venv/Scripts/python.exe", "../venv/bin/python"].find((p) => existsSync(p))?.replace("../", "")
  || "python";

export default defineConfig({
  testDir: "./e2e",
  timeout: 45_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: `http://127.0.0.1:${WEB_PORT}`,
    trace: "retain-on-failure", // a step-by-step replay of any failed test
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: `"${PYTHON}" -m tests.e2e_server --port ${API_PORT}`,
      cwd: "..", // project root, so `tests` and `app` import
      url: `http://127.0.0.1:${API_PORT}/health`,
      timeout: 120_000,
      reuseExistingServer: false,
    },
    {
      command: `npx next dev -p ${WEB_PORT}`,
      url: `http://127.0.0.1:${WEB_PORT}/login`,
      env: { API_URL: `http://127.0.0.1:${API_PORT}`, NEXT_TELEMETRY_DISABLED: "1" },
      timeout: 120_000,
      reuseExistingServer: false,
    },
  ],
});
