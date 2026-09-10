import { test, expect } from "@playwright/test";
import fs from "node:fs/promises";

test("studio playback, edits, history, exports and responsive views", async ({
  page,
  request,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const created = await request.post("/api/projects", {
    data: { name: "Browser verification", starter: true },
  });
  expect(created.ok()).toBeTruthy();
  const project = await created.json();
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Your session" }),
  ).toBeVisible();
  await page.screenshot({
    path: "artifacts/studio-desktop.png",
    fullPage: true,
  });
  const pixels = await page
    .getByLabel("Drums piano roll")
    .evaluate((canvas: HTMLCanvasElement) => {
      const values = canvas
        .getContext("2d")!
        .getImageData(0, 0, canvas.width, canvas.height).data;
      let colored = 0;
      for (let i = 0; i < values.length; i += 4)
        if (values[i] > 100 && values[i] > values[i + 2] * 1.2) colored++;
      return colored;
    });
  expect(pixels).toBeGreaterThan(500);
  await page.getByRole("button", { name: "Play", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Stop playback" }),
  ).toBeVisible();
  await expect
    .poll(() =>
      page
        .locator(".track-controls .meter span")
        .evaluateAll((nodes) =>
          nodes
            .map((n) => parseFloat((n as HTMLElement).style.width))
            .some((w) => w > 5),
        ),
    )
    .toBeTruthy();
  await page.getByRole("button", { name: "Stop", exact: true }).click();
  await page.getByLabel("Tempo", { exact: true }).fill("127");
  await page.getByLabel("Tempo", { exact: true }).press("Enter");
  await expect
    .poll(
      async () =>
        (await (await request.get(`/api/projects/${project.id}`)).json()).tempo,
    )
    .toBe(127);
  await page.getByRole("button", { name: "Undo", exact: true }).click();
  await expect(page.getByLabel("Tempo", { exact: true })).toHaveValue("124");
  await page
    .getByRole("button", { name: "Lead, Main, clip", exact: true })
    .click();
  await page
    .getByRole("button", { name: "New variation", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "New variation", exact: true }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "Sound design", exact: true }).click();
  await page.getByLabel("Instrument preset").selectOption("fm");
  await expect(page.getByLabel("Instrument preset")).toHaveValue("fm");
  await page.getByRole("button", { name: "Filter rise", exact: true }).click();
  await expect(page.locator(".automation-line")).toContainText("cutoff");
  await page.screenshot({ path: "artifacts/studio-sound.png", fullPage: true });
  await page.getByRole("button", { name: "Mixer", exact: true }).click();
  await expect(page.getByLabel("Lead volume")).toBeVisible();
  await page.getByRole("button", { name: "Play", exact: true }).click();
  await expect
    .poll(() =>
      page
        .locator(".master-strip .meter span")
        .evaluate((n) => parseFloat((n as HTMLElement).style.height)),
    )
    .toBeGreaterThan(5);
  await page.getByRole("button", { name: "Stop", exact: true }).click();
  await page.screenshot({ path: "artifacts/studio-mixer.png", fullPage: true });
  await page.getByRole("button", { name: "Recordings", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Melody", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Rhythm", exact: true }).click();
  await expect(page.getByLabel("Recording target")).toHaveValue(
    project.tracks[0].id,
  );
  await page.getByRole("button", { name: "Export", exact: true }).click();
  const midiDownload = page.waitForEvent("download");
  await page
    .getByRole("link", {
      name: "MIDI arrangement All MIDI parts, tempo and sections",
    })
    .click();
  const midi = await midiDownload;
  await midi.saveAs("artifacts/verification.mid");
  expect(
    (await fs.readFile("artifacts/verification.mid")).subarray(0, 4).toString(),
  ).toBe("MThd");
  const waveDownload = page.waitForEvent("download", { timeout: 90_000 });
  await page
    .getByRole("button", { name: "WAV audio Full mix, 44.1 kHz / 16-bit" })
    .click();
  const wav = await waveDownload;
  await wav.saveAs("artifacts/verification.wav");
  expect((await fs.stat("artifacts/verification.wav")).size).toBeGreaterThan(
    1_000_000,
  );
  await page.getByRole("button", { name: "Arrangement", exact: true }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({
    path: "artifacts/studio-mobile.png",
    fullPage: true,
  });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(
    390,
  );
  await page.getByRole("button", { name: "Co-producer", exact: true }).click();
  await expect(
    page.getByLabel("Musical direction", { exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: "artifacts/studio-mobile-chat.png",
    fullPage: true,
  });
  expect(errors).toEqual([]);
});
