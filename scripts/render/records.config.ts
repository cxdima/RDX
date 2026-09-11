import { defineConfig } from "@playwright/test";
import path from "node:path";

// Not part of the test suite: this drives the studio's own audio engine to
// render whole records to WAV, so the musical vocabulary can be judged by ear.
// Its own port and data directory, so it never touches the user's projects.
export default defineConfig({
  testDir: path.resolve("scripts/render"),
  testMatch: "records.spec.ts",
  outputDir: path.resolve("artifacts/render-results"),
  workers: 1,
  timeout: 900_000,
  use: {
    baseURL: "http://127.0.0.1:8767",
    headless: true,
    viewport: { width: 1440, height: 960 },
  },
  webServer: {
    command: `${path.resolve(".venv/bin/python")} -m uvicorn rdx.server:app --host 127.0.0.1 --port 8767`,
    cwd: path.resolve("."),
    url: "http://127.0.0.1:8767/api/status",
    reuseExistingServer: false,
    env: { RDX_DATA_DIR: path.resolve("artifacts/render-data") },
    timeout: 60_000,
  },
});
