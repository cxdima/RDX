import { test, expect } from "@playwright/test";

/**
 * The generators, reached as controls rather than through the model.
 *
 * The Python tests prove a trance melody is stated, repeated, sequenced up,
 * peaked and resolved. What they cannot prove is that a producer sitting in
 * front of the studio can reach any of it: until this panel existed, melody,
 * bassline, kit and harmony were reachable only by typing a sentence and hoping
 * a 4B model recognised which operation was meant.
 *
 * Every assertion here is about the music that came out and is written to hold
 * however many times it has been run before — the studio keeps its projects, so
 * a test that measures a delta from whatever was there passes once and then
 * starts lying.
 */

/** The notes on one track in one section, read back from the API. */
async function notes(
  request: { get: (url: string) => Promise<{ json: () => Promise<any> }> },
  role: string,
  sectionName: string,
): Promise<{ pitch: number; start: number }[]> {
  const projects = await (await request.get("/api/projects")).json();
  const id = (projects.projects ?? projects)[0].id;
  const project = await (await request.get(`/api/projects/${id}`)).json();
  const section = project.sections.find(
    (s: { name: string }) => s.name === sectionName,
  );
  const track = project.tracks.find((t: { role: string }) => t.role === role);
  const clip = track.clips.find(
    (c: { section_id: string }) => c.section_id === section.id,
  );
  return clip ? clip.notes : [];
}

async function settled<T>(read: () => Promise<T>, want: (value: T) => boolean) {
  await expect
    .poll(async () => want(await read()), { timeout: 30_000 })
    .toBe(true);
  return read();
}

test("the cell control decides the rhythm of the melody it writes", async ({
  page,
  request,
}) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Your session" })).toBeVisible(
    {
      timeout: 30_000,
    },
  );
  await page
    .getByRole("button", { name: "Lead, Main, clip", exact: true })
    .click();

  const panel = page.locator(".write-panel");
  await expect(panel).toBeVisible();
  // Every option offered has to exist in Python; the mirror test proves the
  // lists match, and this proves the list reached the browser.
  await expect(panel.locator("select").first().locator("option")).toHaveCount(
    7,
  );

  const write = panel.getByRole("button", { name: "Write the melody" });
  // A pluck is eight notes a bar with gaps; an anthem is three long ones. Both
  // are written here so the comparison is between two things this test did,
  // not against whatever a previous run left behind.
  await panel.locator("select").first().selectOption("pluck");
  await write.click();
  const plucked = await settled(
    () => notes(request, "lead", "Main"),
    (n) => n.length > 24,
  );

  await panel.locator("select").first().selectOption("anthem");
  await write.click();
  const sung = await settled(
    () => notes(request, "lead", "Main"),
    (n) => n.length < plucked.length,
  );

  expect(sung.length).toBeGreaterThan(8); // 8 bars, so at least one a bar
  expect(sung.length).toBeLessThanOrEqual(8 * 3); // and at most the cell's three
});

test("the drum buttons add to the pattern instead of replacing it", async ({
  page,
  request,
}) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Your session" })).toBeVisible(
    {
      timeout: 30_000,
    },
  );
  await page
    .getByRole("button", { name: "Drums, Main, clip", exact: true })
    .click();

  const panel = page.locator(".write-panel");
  await expect(panel.getByRole("button", { name: "Crash" })).toBeVisible();
  const before = await notes(request, "drums", "Main");
  const voices = new Set(before.map((n) => n.pitch));
  expect(voices.size).toBeGreaterThan(2);
  await panel.getByRole("button", { name: "Crash" }).click();

  // Exactly one crash on the downbeat, however many times this has been run:
  // decorating replaces the crash that is there rather than stacking another,
  // and leaves every other voice alone. A pattern rebuilt from a default kit
  // would lose the double claps, which is the bug this guards.
  const after = await settled(
    () => notes(request, "drums", "Main"),
    (n) => n.some((note) => note.pitch === 49),
  );
  expect(after.filter((n) => n.pitch === 49 && n.start < 1)).toHaveLength(1);
  const kept = new Set(after.map((n) => n.pitch));
  for (const voice of voices) expect(kept).toContain(voice);
  expect(after.length).toBeGreaterThanOrEqual(before.length);
});

test("the bassline select writes through on change", async ({
  page,
  request,
}) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Your session" })).toBeVisible(
    {
      timeout: 30_000,
    },
  );
  await page
    .getByRole("button", { name: "Bass, Main, clip", exact: true })
    .click();

  const panel = page.locator(".write-panel");
  const bassline = panel.locator("select").nth(5);

  // Sixteenths: sixteen a bar over eight bars, whatever was there before.
  await bassline.selectOption("sixteenth");
  const run = await settled(
    () => notes(request, "bass", "Main"),
    (n) => n.length > 64,
  );
  expect(run.length).toBe(8 * 16);

  // The placeholder row must not fire an edit of its own.
  await bassline.selectOption("");
  await page.waitForTimeout(1500);
  expect((await notes(request, "bass", "Main")).length).toBe(run.length);
});
