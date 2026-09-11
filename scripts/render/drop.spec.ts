import { test, expect } from "@playwright/test";
import fs from "node:fs";

// Renders one section of a record so a level or balance change can be measured
// in about a minute instead of the nine a whole record takes. This is the loop
// the master chain and the mix balance were tuned in:
//
//   RDX_GENRE=psytrance npm run render:drop            the drop, everything playing
//   RDX_GENRE=trance RDX_SOLO=lead npm run render:drop  one part alone
//   RDX_MASTER=9 npm run render:drop                    try a master gain
//
// then `npm run measure` on the file it leaves in artifacts/drop/.
test.setTimeout(600_000);

const GENRE = process.env.RDX_GENRE || "trance";
const MASTER = process.env.RDX_MASTER ? Number(process.env.RDX_MASTER) : null;
const SOLO = process.env.RDX_SOLO || null; // a role: mute every other track

test(`render a ${GENRE} drop`, async ({ page }) => {
  console.log(
    `RENDERING genre=${GENRE} solo=${SOLO ?? "none"} master=${MASTER ?? "default"}`,
  );
  // A project of this run's own. Opening whichever project was edited last
  // inherits every flag a previous run left on it — one run inherited a solo
  // and rendered three silent tracks that read like a regression in the engine.
  const created = await (
    await page.request.post("/api/projects", {
      data: { name: "render", starter: true },
    })
  ).json();
  const id = created.id;
  let project = created;
  project = await (
    await page.request.post(`/api/projects/${id}/edits`, {
      data: {
        revision: project.revision,
        label: "trance",
        actions: [
          { kind: "record", params: { genre: GENRE } },
          ...(MASTER === null
            ? []
            : [{ kind: "master", params: { volume_db: MASTER } }]),
        ],
      },
    })
  ).json();

  // Keep the Drop and throw the rest away, so the render is short.
  const keep = project.sections.find(
    (s: { name: string }) => s.name === "Drop",
  );
  const drop = await (
    await page.request.post(`/api/projects/${id}/edits`, {
      data: {
        revision: project.revision,
        label: "just the drop",
        actions: project.sections
          .filter((s: { id: string }) => s.id !== keep.id)
          .map((s: { id: string }) => ({
            kind: "arrange",
            section: s.id,
            params: { operation: "remove" },
          })),
      },
    })
  ).json();
  expect(drop.sections).toHaveLength(1);
  if (SOLO) {
    const muted = await (
      await page.request.post(`/api/projects/${id}/edits`, {
        data: {
          revision: drop.revision,
          label: `solo ${SOLO}`,
          actions: drop.tracks
            .filter((t: { role: string }) => t.role !== SOLO)
            .map((t: { id: string }) => ({
              kind: "mix",
              track: t.id,
              params: { mute: true },
            })),
        },
      })
    ).json();
    expect(muted.tracks.filter((t: { mute: boolean }) => !t.mute)).toHaveLength(
      1,
    );
  }

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Your session" })).toBeVisible(
    {
      timeout: 60_000,
    },
  );
  await page.getByRole("button", { name: "Export", exact: true }).click();
  const download = page.waitForEvent("download", { timeout: 540_000 });
  await page.getByRole("button", { name: /WAV audio/ }).click();
  const out = `${process.env.RENDER_DIR}/drop.wav`;
  await (await download).saveAs(out);
  expect(fs.statSync(out).size).toBeGreaterThan(100_000);
});
