import { test, expect } from "@playwright/test";

/**
 * Mix analysis end to end.
 *
 * The Python tests measure synthetic audio. This proves the path a producer
 * actually uses: the browser renders every track, uploads the stems, the
 * server measures them, and the reading comes back and appears on screen.
 */
test("the studio renders the mix, measures it, and reports what it found", async ({
  page,
  request,
}) => {
  test.setTimeout(180_000);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));

  const created = await request.post("/api/projects", {
    data: { name: "Mix measurement", starter: true },
  });
  const project = await created.json();
  // Trim to one short section: the measurement is the same either way, and a
  // four-bar render keeps the test honest about speed rather than patient.
  let revision = project.revision;
  for (const section of project.sections.slice(1)) {
    const result = await request.post(`/api/projects/${project.id}/edits`, {
      data: {
        revision,
        actions: [
          {
            kind: "arrange",
            section: section.id,
            params: { operation: "remove" },
          },
        ],
        label: "Trim",
      },
    });
    revision = (await result.json()).revision;
  }

  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Your session" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Mixer", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Mix analysis" }),
  ).toBeVisible();
  await expect(page.getByText("Not measured yet.")).toBeVisible();

  await page.getByRole("button", { name: "Analyse the mix" }).click();
  await expect(page.getByText("LUFS")).toBeVisible({ timeout: 150_000 });

  // Every band adds up to the whole spectrum, and the reading is real numbers.
  const shares = await page
    .locator(".mix-numbers span")
    .filter({ hasText: /%$|%/ })
    .evaluateAll((nodes) =>
      nodes
        .map((n) => parseInt(n.querySelector("output")?.textContent ?? "", 10))
        .filter((v) => !Number.isNaN(v)),
    );
  expect(shares.length).toBeGreaterThanOrEqual(5);
  expect(shares.reduce((sum, v) => sum + v, 0)).toBeGreaterThan(90);

  // Captured with the reading on screen rather than after it is spent.
  await page.screenshot({ path: "artifacts/studio-mix-analysis.png" });

  const findings = page.locator(".mix-findings li");
  if (await findings.count()) {
    // Whatever it found, it has to be actionable and it has to cite a number.
    await expect(findings.first()).toContainText(/\d/);
    await findings.first().getByRole("button", { name: "Fix" }).click();
    await expect
      .poll(
        async () =>
          (await (await request.get(`/api/projects/${project.id}`)).json())
            .revision,
      )
      .toBeGreaterThan(revision);
    // The edit invalidates the measurement rather than leaving it looking current.
    await expect(page.getByText("Analyse it again.")).toBeVisible();
  } else {
    await expect(
      page.getByText("Nothing in this mix measures as a problem."),
    ).toBeVisible();
  }

  expect(errors).toEqual([]);
});
