import {
  test as base,
  expect,
  type APIRequestContext,
  type Page,
} from "@playwright/test";
import type { Project } from "../../src/types";

const test = base.extend<{ projectId: string }>({
  projectId: async ({ request }, use) => {
    const response = await request.post("/api/projects", {
      data: { name: "Generator test", starter: true },
    });
    expect(response.ok()).toBeTruthy();
    const project: Project = await response.json();
    await use(project.id);
  },
});

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
  request: APIRequestContext,
  id: string,
  role: string,
  sectionName: string,
): Promise<{ pitch: number; start: number }[]> {
  const project: Project = await (
    await request.get(`/api/projects/${id}`)
  ).json();
  const section = project.sections.find(
    (s: { name: string }) => s.name === sectionName,
  )!;
  const track = project.tracks.find((t: { role: string }) => t.role === role)!;
  const clip = track.clips.find(
    (c: { section_id: string }) => c.section_id === section.id,
  );
  return clip ? clip.notes : [];
}

async function edited(page: Page, id: string, act: () => Promise<unknown>) {
  const response = page.waitForResponse(
    (r) =>
      r.url().endsWith(`/api/projects/${id}/edits`) &&
      r.request().method() === "POST",
  );
  await act();
  expect((await response).ok()).toBeTruthy();
}

test("the cell control decides the rhythm of the melody it writes", async ({
  page,
  request,
  projectId,
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
  await edited(page, projectId, () => write.click());
  const plucked = await notes(request, projectId, "lead", "Main");
  expect(plucked.length).toBeGreaterThan(24);

  await panel.locator("select").first().selectOption("anthem");
  await edited(page, projectId, () => write.click());
  const sung = await notes(request, projectId, "lead", "Main");
  expect(sung.length).toBeLessThan(plucked.length);

  expect(sung.length).toBeGreaterThan(8); // 8 bars, so at least one a bar
  expect(sung.length).toBeLessThanOrEqual(8 * 3); // and at most the cell's three
});

test("the drum buttons add to the pattern instead of replacing it", async ({
  page,
  request,
  projectId,
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
  const before = await notes(request, projectId, "drums", "Main");
  const voices = new Set(before.map((n) => n.pitch));
  expect(voices.size).toBeGreaterThan(2);
  await edited(page, projectId, () =>
    panel.getByRole("button", { name: "Crash" }).click(),
  );

  // Exactly one crash on the downbeat, however many times this has been run:
  // decorating replaces the crash that is there rather than stacking another,
  // and leaves every other voice alone. A pattern rebuilt from a default kit
  // would lose the double claps, which is the bug this guards.
  const after = await notes(request, projectId, "drums", "Main");
  expect(after.filter((n) => n.pitch === 49 && n.start < 1)).toHaveLength(1);
  const kept = new Set(after.map((n) => n.pitch));
  for (const voice of voices) expect(kept).toContain(voice);
  expect(after.length).toBeGreaterThanOrEqual(before.length);
});

test("the bassline select writes through on change", async ({
  page,
  request,
  projectId,
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
  await edited(page, projectId, () => bassline.selectOption("sixteenth"));
  const run = await notes(request, projectId, "bass", "Main");
  expect(run.length).toBe(8 * 16);

  // The placeholder row must not fire an edit of its own.
  // Bracket the placeholder selection with a real, completed edit. If the
  // placeholder also submits, the request log will contain a second POST.
  const posts: string[] = [];
  page.on("request", (r) => {
    if (
      r.method() === "POST" &&
      r.url().endsWith(`/api/projects/${projectId}/edits`)
    )
      posts.push(r.url());
  });
  await bassline.selectOption("");
  await edited(page, projectId, () => bassline.selectOption("offbeat"));
  expect(posts).toHaveLength(1);
  expect(
    (await notes(request, projectId, "bass", "Main")).every(
      (n) => n.start % 1 === 0.5,
    ),
  ).toBe(true);
});
