import { defineConfig } from "@playwright/test";
import path from "node:path";

export default defineConfig({
  testDir: "./tests/browser",
  outputDir: "./artifacts/browser-results",
  workers: 1,
  // Audio is the slow part: starting playback builds every voice and generates
  // reverb impulse responses, and the suite is usually run while the machine is
  // also training or rendering. Individual waits are tighter than this.
  timeout: 120_000,
  use: {
    baseURL: "http://127.0.0.1:8766",
    headless: true,
    viewport: { width: 1440, height: 960 },
    trace: "retain-on-failure",
  },
  webServer: {
    // Wiped here rather than in a globalSetup, which Playwright runs *after*
    // the server is up — it deleted the directory the server had just made and
    // every stem upload failed. The studio opens whichever project was edited
    // last, so a run that leaves edits behind decides what the next run opens:
    // writing a melody into the shared project made a later run of
    // studio.spec.ts fail looking for an element the edits had moved. A suite
    // whose result depends on how often it has been run is worse than none.
    command:
      "npm run build && rm -rf .cache/browser-test && .venv/bin/python -m uvicorn rdx.server:app --host 127.0.0.1 --port 8766",
    url: "http://127.0.0.1:8766/api/status",
    reuseExistingServer: false,
    env: { RDX_DATA_DIR: path.resolve(".cache/browser-test") },
    timeout: 60_000,
  },
});
