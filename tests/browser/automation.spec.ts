import { test, expect } from "@playwright/test";

/**
 * Automation belongs to the section it was drawn in.
 *
 * A Web Audio parameter holds whatever value it was last given, forever. So a
 * lane that ends at -60 dB — which is exactly what a buildup's cut before the
 * drop is — stayed in force for every section after it, and the rest of the
 * record never made a sound. A rendered psytrance record measured -38 dBFS
 * through its intro and then -75 dBFS through its drop.
 *
 * Nothing that reads the project can see this: the notes are all there and the
 * automation is correct. It is only audible, so this test listens.
 */
function sound(preset: string) {
  return {
    preset,
    cutoff: 12000,
    resonance: 1,
    attack: 0.001,
    decay: 0.3,
    sustain: 0.9,
    release: 0.1,
    filter_env: 0,
    filter_decay: 0.3,
    wave: "preset",
    unison: 1,
    spread: 0,
    sub: 0,
    octave: 0,
    reverb: 0,
    delay: 0,
    drive: 0,
    crush: 0,
    low: 0,
    mid: 0,
    high: 0,
    chorus: 0,
    flanger: 0,
    phaser: 0,
    autopan: 0,
    motion_rate: 0.4,
    width: 0,
    glide: 0,
    lfo_target: "off",
    lfo_depth: 0,
    lfo_rate: 4,
  };
}

/** Two bars of held notes. The first bar fades itself to silence, the way a
 *  buildup cuts before a drop; the second automates nothing at all. */
function project() {
  const cut = { id: "sec000000001", name: "Build", bars: 1, energy: 0.8 };
  const drop = { id: "sec000000002", name: "Drop", bars: 1, energy: 1 };
  const note = (id: string) => ({
    id,
    pitch: 57,
    start: 0,
    duration: 3.9,
    velocity: 100,
  });
  return {
    id: "prj000000002",
    name: "Automation scope",
    revision: 0,
    tempo: 120,
    key: "A",
    scale: "minor",
    seed: 1,
    sections: [cut, drop],
    master: { volume_db: 0, ceiling: 0, compression: 0 },
    tracks: [
      {
        id: "trklead00001",
        name: "Lead",
        role: "lead",
        color: "#bde66c",
        volume_db: -6,
        pan: 0,
        mute: false,
        solo: false,
        locked: false,
        sound: sound("sine"),
        kit: null,
        sidechain: null,
        clips: [
          {
            id: "clpcut000001",
            name: "Build",
            section_id: cut.id,
            notes: [note("not000000001")],
            audio_id: null,
            audio_offset: 0,
          },
          {
            id: "clpdrop00001",
            name: "Drop",
            section_id: drop.id,
            notes: [note("not000000002")],
            audio_id: null,
            audio_offset: 0,
          },
        ],
        automation: [
          {
            id: "aut000000001",
            section_id: cut.id,
            parameter: "volume_db",
            points: [
              [0, -6],
              [3, -60],
            ],
          },
        ],
      },
    ],
  };
}

test("a section that automates nothing plays at full level", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Your session" }),
  ).toBeVisible();

  const levels = await page.evaluate(async (source) => {
    const blob = await window.rdx.audio.render(source as never);
    const view = new DataView(await blob.arrayBuffer());
    const rate = view.getUint32(24, true);
    const samples = (view.byteLength - 44) / 4;
    const level = (from: number, to: number) => {
      let sum = 0;
      let counted = 0;
      for (
        let i = Math.round(from * rate);
        i < Math.min(Math.round(to * rate), samples);
        i++
      ) {
        const value = view.getInt16(44 + i * 4, true) / 32768;
        sum += value * value;
        counted++;
      }
      return counted ? Math.sqrt(sum / counted) : 0;
    };
    // 120 BPM: a bar is two seconds. Measure the opening of the faded bar, its
    // silent end, and the middle of the bar that follows it.
    return {
      opening: level(0.1, 0.4),
      faded: level(1.8, 1.95),
      after: level(2.3, 2.8),
    };
  }, project());

  expect(levels.opening).toBeGreaterThan(0.01);
  expect(levels.faded).toBeLessThan(levels.opening * 0.2);
  // The whole point: the next section never asked to be quiet, so it is not.
  expect(levels.after).toBeGreaterThan(levels.opening * 0.5);
  expect(errors).toEqual([]);
});

test("a finished record is loud enough to be a record, and does not clip", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Your session" }),
  ).toBeVisible();

  // The master chain was a compressor into a limiter with nothing in between.
  // Both only ever turn things down, so the ceiling was unreachable and every
  // record rendered about 20 dB below a normal one. a producer's own
  // description of mastering is compression to bring loudness up and a limiter
  // to get as loud as possible *without distorting*, so this measures both.
  // The shared fixture flattens the master to zeroes so the automation test
  // measures the fader alone. This one is about the master chain itself, so it
  // uses the real defaults from rdx/domain.py.
  const loud = {
    ...project(),
    master: { volume_db: 8, ceiling: -1, compression: -18 },
  };
  const measured = await page.evaluate(async (source) => {
    const blob = await window.rdx.audio.render(source as never);
    const view = new DataView(await blob.arrayBuffer());
    const total = (view.byteLength - 44) / 4;
    let sum = 0;
    let peak = 0;
    let clipped = 0;
    for (let i = 0; i < total; i++) {
      const value = view.getInt16(44 + i * 4, true) / 32768;
      sum += value * value;
      peak = Math.max(peak, Math.abs(value));
      if (Math.abs(value) >= 0.999) clipped++;
    }
    return { rms: Math.sqrt(sum / total), peak, clipped };
  }, loud);

  expect(measured.clipped).toBe(0);
  expect(measured.peak).toBeLessThanOrEqual(1);
  // Well above the -34 LUFS the purely-downward chain produced. A held note at
  // -6 dB through the whole chain has to arrive somewhere near full scale.
  expect(20 * Math.log10(measured.peak)).toBeGreaterThan(-12);
  expect(errors).toEqual([]);
});

test("nothing gets past the ceiling, however hard the master is pushed", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Your session" }),
  ).toBeVisible();

  // Tone's limiter is a fast compressor, not a brickwall: on sub-heavy material
  // a few hundred samples per record still went past full scale. A soft clip
  // at the ceiling catches the overshoot. Pushed with +12 dB of master gain,
  // the loudest thing the model allows, the output must still never exceed the
  // ceiling — and must still be a signal, not a flat line.
  const pushed = {
    ...project(),
    master: { volume_db: 12, ceiling: -1, compression: -18 },
  };
  const measured = await page.evaluate(async (source) => {
    const blob = await window.rdx.audio.render(source as never);
    const view = new DataView(await blob.arrayBuffer());
    const total = (view.byteLength - 44) / 4;
    let peak = 0;
    let over = 0;
    let sum = 0;
    for (let i = 0; i < total; i++) {
      const value = Math.abs(view.getInt16(44 + i * 4, true) / 32768);
      peak = Math.max(peak, value);
      if (value > 0.891) over++; // -1 dBFS is 0.891 linear
      sum += value * value;
    }
    return { peak, over, rms: Math.sqrt(sum / total) };
  }, pushed);

  expect(measured.over).toBe(0);
  expect(measured.peak).toBeLessThanOrEqual(0.892);
  expect(measured.rms).toBeGreaterThan(0.1); // loud, not silenced
  expect(errors).toEqual([]);
});

test("a late automation lane starts from this section's resting level", async ({
  page,
}) => {
  await page.goto("/");
  const source = project();
  source.tracks[0].automation.push({
    id: "aut000000002",
    section_id: source.sections[1].id,
    parameter: "volume_db",
    points: [
      [3, -6],
      [4, -60],
    ],
  });
  const level = await page.evaluate(async (source) => {
    const view = new DataView(
      await (await window.rdx.audio.render(source as never)).arrayBuffer(),
    );
    const rate = view.getUint32(24, true);
    let power = 0;
    for (let i = Math.round(2.3 * rate); i < Math.round(2.8 * rate); i++) {
      power += (view.getInt16(44 + i * 4, true) / 32768) ** 2;
    }
    return Math.sqrt(power / (rate * 0.5));
  }, source);
  expect(level).toBeGreaterThan(0.03);
});

test("automation in a later section does not change the resting sound", async ({
  page,
}) => {
  await page.goto("/");
  for (const [parameter, value] of [
    ["width", 0.4],
    ["drive", 0.1],
    ["crush", 0.8],
  ] as const) {
    const source = project();
    source.tracks[0].automation = [];
    source.tracks[0].sound[parameter] = value;
    const difference = await page.evaluate(
      async ({ source, parameter }) => {
        const render = async () =>
          new DataView(
            await (
              await window.rdx.audio.render(source as never)
            ).arrayBuffer(),
          );
        const plain = await render();
        source.tracks[0].automation.push({
          id: "aut000000002",
          section_id: source.sections[1].id,
          parameter,
          points: [
            [0, 0],
            [4, 0],
          ],
        });
        const automated = await render();
        const rate = plain.getUint32(24, true);
        let delta = 0;
        let power = 0;
        for (let i = Math.round(0.3 * rate); i < Math.round(rate); i++) {
          const a = plain.getInt16(44 + i * 4, true);
          const b = automated.getInt16(44 + i * 4, true);
          delta += (a - b) ** 2;
          power += a ** 2;
        }
        return Math.sqrt(delta / power);
      },
      { source, parameter },
    );
    expect(
      difference,
      `${parameter} changed the unautomated section`,
    ).toBeLessThan(0.002);
  }
});

test("drum transients stay below the chosen sample ceiling", async ({
  page,
}) => {
  await page.goto("/");
  const source = project();
  source.master = { volume_db: 12, ceiling: -6, compression: -18 };
  source.tracks[0].role = "drums";
  source.tracks[0].automation = [];
  source.tracks[0].clips.forEach((clip) => {
    clip.notes = [0, 1, 2, 3].flatMap((start) =>
      [36, 38, 42].map((pitch) => ({
        id: `n${start}${pitch}`,
        pitch,
        start,
        duration: 0.1,
        velocity: 127,
      })),
    );
  });
  const peak = await page.evaluate(async (source) => {
    const view = new DataView(
      await (await window.rdx.audio.render(source as never)).arrayBuffer(),
    );
    let peak = 0;
    for (let offset = 44; offset < view.byteLength; offset += 2)
      peak = Math.max(peak, Math.abs(view.getInt16(offset, true)) / 32768);
    return peak;
  }, source);
  expect(peak).toBeGreaterThan(0.4);
  expect(peak).toBeLessThanOrEqual(10 ** (-6 / 20) + 1 / 32768);
});

test("a failed audio export does not break playback of another project", async ({
  page,
}) => {
  await page.goto("/");
  await page.route("**/api/audio/abcdef123456/wave", (route) =>
    route.fulfill({ status: 404, body: "missing" }),
  );
  const failed = await page.evaluate(async (source) => {
    const clip = source.tracks[0].clips[0];
    const broken = {
      ...source,
      tracks: [
        {
          ...source.tracks[0],
          role: "audio",
          clips: [{ ...clip, audio_id: "abcdef123456", notes: [] }],
        },
      ],
    };
    let failed = false;
    try {
      await window.rdx.audio.render(broken as never);
    } catch {
      failed = true;
    }
    await window.rdx.audio.play(source as never, source.sections[0].id, false);
    return failed;
  }, project());
  expect(failed).toBe(true);
  await expect
    .poll(() => page.evaluate(() => window.rdx.audio.seconds))
    .toBeGreaterThan(0.1);
  await page.evaluate(() => window.rdx.audio.stop());
});
