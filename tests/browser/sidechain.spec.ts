import { test, expect } from "@playwright/test";

/**
 * Ducking, verified by listening rather than by reading the code.
 *
 * The Python tests prove the curve is right and that the browser's copy of it
 * is identical. What they cannot prove is that the audio engine actually puts
 * that curve in the signal path. So this renders a real mix and measures it:
 * a bass ducked hard under a four-on-the-floor kick must be quiet on each beat
 * and loud between them.
 */

/** A project with one bar of kicks and a bass note held right through it. */
function project(ducked: boolean) {
  const section = { id: "sec000000001", name: "Main", bars: 1, energy: 1 };
  const sound = (preset: string) => ({
    preset,
    cutoff: 12000,
    resonance: 1,
    attack: 0.001,
    release: 0.1,
    reverb: 0,
    delay: 0,
    drive: 0,
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
  });
  const kicks = [0, 1, 2, 3].map((beat, index) => ({
    id: `kick${index}`,
    pitch: 36,
    start: beat,
    duration: 0.12,
    velocity: 100,
  }));
  return {
    id: "prj000000001",
    name: "Ducking check",
    revision: 0,
    tempo: 120,
    key: "A",
    scale: "minor",
    seed: 1,
    sections: [section],
    master: { volume_db: 0, ceiling: 0, compression: 0 },
    tracks: [
      {
        id: "trkdrums0001",
        name: "Drums",
        role: "drums",
        color: "#ed987b",
        volume_db: -6,
        pan: 0,
        // Muted: ducking follows the source track's notes, not its audio, so
        // it must still fire. That is what makes a silent trigger track work.
        mute: true,
        solo: false,
        locked: false,
        sound: sound("drumkit"),
        sidechain: null,
        clips: [
          {
            id: "clpdrums0001",
            name: "Drums",
            section_id: section.id,
            notes: kicks,
            audio_id: null,
            audio_offset: 0,
          },
        ],
        automation: [],
      },
      {
        id: "trkbass00001",
        name: "Bass",
        role: "bass",
        color: "#bde66c",
        volume_db: -6,
        pan: 0,
        mute: false,
        solo: false,
        locked: false,
        sound: sound("sine"),
        sidechain: ducked
          ? {
              source: "trkdrums0001",
              amount: 0.95,
              attack: 0.01,
              release: 0.9,
              curve: "linear",
              trigger: "kick",
            }
          : null,
        clips: [
          {
            id: "clpbass00001",
            name: "Bass",
            section_id: section.id,
            notes: [
              {
                id: "bassnote001",
                pitch: 45,
                start: 0,
                duration: 4,
                velocity: 110,
              },
            ],
            audio_id: null,
            audio_offset: 0,
          },
        ],
        automation: [],
      },
    ],
  };
}

test("a ducked bass really does drop away under every kick", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Your session" }),
  ).toBeVisible();

  /** Loudness on each beat and between the beats, from the rendered audio. */
  const measure = async (input: ReturnType<typeof project>) =>
    page.evaluate(async (source) => {
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
      // 120 BPM, so a beat is half a second. Sample just after each kick and
      // just before the next one, where the level should have recovered.
      const onBeats = [0, 1, 2, 3].map((beat) =>
        level(beat * 0.5 + 0.02, beat * 0.5 + 0.06),
      );
      const between = [0, 1, 2, 3].map((beat) =>
        level(beat * 0.5 + 0.4, beat * 0.5 + 0.44),
      );
      const average = (values: number[]) =>
        values.reduce((sum, value) => sum + value, 0) / values.length;
      return { onBeats: average(onBeats), between: average(between) };
    }, input);

  const ducked = await measure(project(true));
  const flat = await measure(project(false));

  expect(flat.between).toBeGreaterThan(0.005);
  // Without ducking a held note is level throughout; with it, the beats are
  // buried. 12 dB is a conservative floor for a 26 dB setting.
  expect(flat.onBeats / flat.between).toBeGreaterThan(0.6);
  expect(ducked.onBeats / ducked.between).toBeLessThan(0.25);
  expect(errors).toEqual([]);
});
