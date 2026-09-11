import { test, expect } from "@playwright/test";

/**
 * Sound design, verified by listening rather than by reading the parameters.
 *
 * The Python tests prove a patch writes the settings it claims. What they
 * cannot prove is that those settings reach the audio — a filter envelope that
 * is stored and never wired to anything looks identical in a project file.
 *
 * So this renders real audio through the real engine and measures it. The
 * measurement is the zero-crossing rate, which is a cheap and honest proxy for
 * brightness: a sine crosses zero twice per cycle, an open saw far more often.
 *
 * Projects come from the API rather than from a fixture here, so this cannot
 * drift out of date when the Sound model gains a field — which has already
 * happened once.
 */

/** How often the waveform crosses zero, over a window given in seconds. */
const MEASURE = `(view, rate, from, to) => {
  const samples = (view.byteLength - 44) / 4;
  const start = Math.min(Math.round(from * rate), samples);
  const end = Math.min(Math.round(to * rate), samples);
  let crossings = 0;
  let energy = 0;
  let previous = 0;
  for (let i = start; i < end; i++) {
    const value = view.getInt16(44 + i * 4, true) / 32768;
    energy += value * value;
    if (i > start && value !== 0 && Math.sign(value) !== Math.sign(previous)) crossings++;
    if (value !== 0) previous = value;
  }
  const seconds = (end - start) / rate;
  return { brightness: crossings / Math.max(seconds, 1e-9), level: Math.sqrt(energy / Math.max(end - start, 1)) };
}`;

async function renderAndMeasure(
  page: import("@playwright/test").Page,
  project: unknown,
  from: number,
  to: number,
) {
  return page.evaluate(
    async ([source, measure, span]) => {
      const blob = await window.rdx.audio.render(source as never);
      const view = new DataView(await blob.arrayBuffer());
      const rate = view.getUint32(24, true);
      const [start, end] = span as number[];
      return (0, eval)(measure as string)(view, rate, start, end) as {
        brightness: number;
        level: number;
      };
    },
    [project, MEASURE, [from, to]] as const,
  );
}

/** One held note on the lead, alone, so the measurement is of one voice. */
async function soloLeadProject(
  request: import("@playwright/test").APIRequestContext,
  name: string,
  soundParams: Record<string, unknown>,
) {
  const created = await request.post("/api/projects", {
    data: { name, starter: false },
  });
  const project = await created.json();
  const section = project.sections[0];
  const lead = project.tracks.find((t: { role: string }) => t.role === "lead");
  const others = project.tracks.filter((t: { id: string }) => t.id !== lead.id);
  const result = await request.post(`/api/projects/${project.id}/edits`, {
    data: {
      revision: project.revision,
      label: "Set up",
      actions: [
        ...others.map((t: { id: string }) => ({
          kind: "mix",
          track: t.id,
          params: { mute: true },
        })),
        { kind: "sound", track: lead.id, params: soundParams },
        {
          kind: "notes",
          track: lead.id,
          section: section.id,
          params: {
            operation: "replace",
            notes: [{ pitch: 57, start: 0, duration: 3.5, velocity: 110 }],
          },
        },
        {
          kind: "arrange",
          section: section.id,
          params: { operation: "update", bars: 1 },
        },
      ],
    },
  });
  expect(result.ok(), await result.text()).toBeTruthy();
  return result.json();
}

test("a patch changes what comes out of the speakers, not just the file", async ({
  page,
  request,
}) => {
  test.setTimeout(120_000);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Your session" }),
  ).toBeVisible();

  // Reverb and echo are switched off on both. Their tails vary between
  // renders — a reverb's impulse response is generated asynchronously and may
  // not be ready inside an offline render — and this test is about the
  // oscillator, not the space around it.
  const dry = { reverb: 0, delay: 0, filter_env: 0 };
  const sub = await soloLeadProject(request, "Sub", {
    ...dry,
    preset: "sub",
    wave: "sine",
    cutoff: 200,
  });
  const bright = await soloLeadProject(request, "Bright", {
    ...dry,
    preset: "saw",
    wave: "saw",
    cutoff: 16000,
  });

  const quiet = await renderAndMeasure(page, sub, 0.1, 1.5);
  const open = await renderAndMeasure(page, bright, 0.1, 1.5);
  expect(quiet.level).toBeGreaterThan(0.001);
  expect(open.level).toBeGreaterThan(0.001);

  // The note is A3, 220 Hz. A sine crosses zero twice a cycle and nothing
  // else does, so a filtered sine has to measure 440 — which also proves the
  // measurement itself is real rather than an arbitrary number to compare.
  expect(quiet.brightness).toBeGreaterThan(400);
  expect(quiet.brightness).toBeLessThan(480);
  // An open saw carries its harmonics, so it must be well clear of that.
  expect(open.brightness).toBeGreaterThan(quiet.brightness * 2);
  expect(errors).toEqual([]);
});

test("a filter envelope really closes over the length of a note", async ({
  page,
  request,
}) => {
  test.setTimeout(120_000);
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Your session" }),
  ).toBeVisible();

  const snapping = await soloLeadProject(request, "Envelope", {
    reverb: 0,
    delay: 0,
    preset: "saw",
    wave: "saw",
    cutoff: 900,
    resonance: 6,
    filter_env: 0.9,
    filter_decay: 0.35,
    attack: 0.002,
    sustain: 0.9,
    decay: 0.3,
  });

  const opening = await renderAndMeasure(page, snapping, 0.01, 0.1);
  const closed = await renderAndMeasure(page, snapping, 1.2, 1.6);
  // The envelope opens the filter on the attack and lets it shut. If the
  // setting were stored but never wired up, these two would match.
  expect(opening.brightness).toBeGreaterThan(closed.brightness * 1.5);
});

test("an 808 kick rings longer than a 909 kick in the audio", async ({
  page,
  request,
}) => {
  test.setTimeout(120_000);
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Your session" }),
  ).toBeVisible();

  const kickOnly = async (machine: string) => {
    const created = await request.post("/api/projects", {
      data: { name: `Kick ${machine}`, starter: false },
    });
    const project = await created.json();
    const section = project.sections[0];
    const drums = project.tracks.find(
      (t: { role: string }) => t.role === "drums",
    );
    const others = project.tracks.filter(
      (t: { id: string }) => t.id !== drums.id,
    );
    const result = await request.post(`/api/projects/${project.id}/edits`, {
      data: {
        revision: project.revision,
        label: "Kick",
        actions: [
          ...others.map((t: { id: string }) => ({
            kind: "mix",
            track: t.id,
            params: { mute: true },
          })),
          { kind: "kit_sound", track: drums.id, params: { machine } },
          {
            kind: "notes",
            track: drums.id,
            section: section.id,
            params: {
              operation: "replace",
              notes: [{ pitch: 36, start: 0, duration: 0.12, velocity: 120 }],
            },
          },
          {
            kind: "arrange",
            section: section.id,
            params: { operation: "update", bars: 1 },
          },
        ],
      },
    });
    expect(result.ok(), await result.text()).toBeTruthy();
    return result.json();
  };

  // Half a second after the hit, a 909 has gone and an 808 is still going.
  const nine = await renderAndMeasure(page, await kickOnly("909"), 0.45, 0.7);
  const eight = await renderAndMeasure(page, await kickOnly("808"), 0.45, 0.7);
  expect(eight.level).toBeGreaterThan(nine.level * 2);
});
