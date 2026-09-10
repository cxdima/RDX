import { defineConfig } from "@playwright/test";
import path from "node:path";

export default defineConfig({
  testDir: "./tests/browser",
  outputDir: "./artifacts/browser-results",
  workers: 1,
  timeout: 60_000,
  use: {
    baseURL: "http://127.0.0.1:8766",
    headless: true,
    viewport: { width: 1440, height: 960 },
    trace: "retain-on-failure",
  },
  webServer: {
    command:
      ".venv/bin/python -m uvicorn rdx.server:app --host 127.0.0.1 --port 8766",
    url: "http://127.0.0.1:8766/api/status",
    reuseExistingServer: false,
    env: { RDX_DATA_DIR: path.resolve(".cache/browser-test") },
    timeout: 30_000,
  },
});
