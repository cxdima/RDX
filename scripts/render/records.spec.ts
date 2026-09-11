import { test, expect } from "@playwright/test";
import fs from "node:fs";

// Renders whole records to WAV through the studio's own audio engine, so the
// musical work can be judged by ear rather than by reading note numbers.
//
// Not part of `npm run test:browser` — it takes about ten minutes per record
// and asserts almost nothing. Its value is the file it leaves behind. Run it
// with `npm run render`, then listen, or measure what comes out:
//
//   RDX_GENRES=techno npm run render
//
// This is how the automation-scope bug was found. Every Python test passed and
// the record was silent from the first drop onward; nothing that reads a
// project can see that, and nobody had listened to a whole one.
test.setTimeout(2_400_000);

const GENRES = (process.env.RDX_GENRES || "trance,psytrance").split(",");

for (const genre of GENRES) {
  test(`render a ${genre} record`, async ({ page }) => {
    // A project of this run's own. Opening whichever project was edited last
    // inherits every flag a previous run left on it — one run inherited a solo
    // and rendered three silent tracks that read like a regression in the engine.
    const created = await (
      await page.request.post("/api/projects", {
        data: { name: `render ${genre}`, starter: true },
      })
    ).json();
    const id = created.id;
    let project = created;
    project = await (
      await page.request.post(`/api/projects/${id}/edits`, {
        data: {
          revision: project.revision,
          label: `${genre} record`,
          actions: [{ kind: "record", params: { genre } }],
        },
      })
    ).json();
    expect(project.sections.length).toBeGreaterThan(3);

    await page.goto("/");
    await expect(
      page.getByRole("heading", { name: "Your session" }),
    ).toBeVisible({ timeout: 60_000 });
    await page.getByRole("button", { name: "Export", exact: true }).click();
    const download = page.waitForEvent("download", { timeout: 2_100_000 });
    await page.getByRole("button", { name: /WAV audio/ }).click();
    const file = await download;
    const out = `${process.env.RENDER_DIR}/${genre}.wav`;
    await file.saveAs(out);
    expect(fs.statSync(out).size).toBeGreaterThan(100_000);
  });
}
