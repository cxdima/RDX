import type { Note, Sidechain, Track } from "../types";

/**
 * Ducking, mirrored from rdx/musical/sidechain.py.
 *
 * The Python module is the source of truth: it decides what "pump" means and
 * generates the same curve for tests and for anything RDX exports. This file
 * exists so playback hears exactly that, and tests/test_musical.py asserts the
 * two shape tables stay identical, so they cannot drift apart in silence.
 */

/** Drum voices that can key a duck, by the name a producer would say. */
export const TRIGGERS: Record<string, number | null> = {
  kick: 36,
  snare: 38,
  clap: 39,
  rim: 37,
  hat: 42,
  all: null,
};

export type Shape = {
  amount: number;
  release: number;
  attack: number;
  curve: string;
};

export const SHAPES: Record<string, Shape> = {
  pump: { amount: 0.75, release: 0.95, attack: 0.02, curve: "exponential" },
  tight: { amount: 0.55, release: 0.35, attack: 0.008, curve: "exponential" },
  gentle: { amount: 0.3, release: 0.6, attack: 0.02, curve: "exponential" },
  breathing: { amount: 0.65, release: 1.9, attack: 0.02, curve: "smooth" },
  extreme: { amount: 0.93, release: 1.1, attack: 0.02, curve: "smooth" },
  eighth: { amount: 0.7, release: 0.48, attack: 0.006, curve: "exponential" },
};

/** Gain part-way through the recovery, from the floor back to unity. */
export function recover(
  progress: number,
  floor: number,
  curve: string,
): number {
  if (progress <= 0) return floor;
  if (progress >= 1) return 1;
  const span = 1 - floor;
  if (curve === "linear") return floor + span * progress;
  if (curve === "smooth")
    return floor + (span * (1 - Math.cos(Math.PI * progress))) / 2;
  return floor + (span * (1 - Math.exp(-4 * progress))) / (1 - Math.exp(-4));
}

/** The moments a duck fires, from the notes of the source part. */
export function triggerBeats(notes: Note[], trigger: string): number[] {
  const pitch = TRIGGERS[trigger];
  const beats = notes
    .filter((note) => pitch === null || note.pitch === pitch)
    .map((note) => note.start)
    .sort((a, b) => a - b);
  const unique: number[] = [];
  for (const beat of beats)
    if (!unique.length || beat - unique[unique.length - 1] > 0.125)
      unique.push(beat);
  return unique;
}

const round = (value: number, places: number) => {
  const factor = 10 ** places;
  return Math.round(value * factor) / factor;
};

/** The gain curve for one section, as [beat, gain] pairs. */
export function duckingPoints(
  triggers: number[],
  length: number,
  { amount, attack, release, curve }: Shape,
  steps = 8,
): [number, number][] {
  const floor = round(1 - amount, 6);
  const points: [number, number][] = [];
  const add = (beat: number, gain: number) => {
    const at = round(Math.min(Math.max(beat, 0), length), 4);
    const value = round(Math.min(Math.max(gain, 0), 1), 5);
    if (points.length && Math.abs(points[points.length - 1][0] - at) < 1e-6)
      points[points.length - 1][1] = value;
    else points.push([at, value]);
  };

  const inside = triggers.filter((t) => t >= -attack && t < length);
  if (!inside.length)
    return [
      [0, 1],
      [round(length, 4), 1],
    ];
  if (inside[0] > 1e-6) add(0, 1);
  inside.forEach((beat, index) => {
    const following =
      index + 1 < inside.length ? inside[index + 1] : length + attack;
    add(
      beat,
      index === 0 || beat - inside[index - 1] > attack + 1e-9 ? 1 : floor,
    );
    const landing = Math.min(beat + attack, following);
    add(landing, floor);
    for (let step = 1; step <= steps; step++) {
      const moment = landing + (release * step) / steps;
      if (moment >= following - 1e-9 || moment > length) break;
      add(moment, recover(step / steps, floor, curve));
    }
    if (landing + release < following - 1e-9 && landing + release <= length)
      add(landing + release, 1);
  });
  const last = points[points.length - 1];
  if (last[0] < length - 1e-6) add(length, last[1] >= 1 ? last[1] : 1);
  return points;
}

/** The notes that will trigger a track's ducking inside one section. */
export function sourceNotes(
  setting: Sidechain,
  tracks: Track[],
  sectionId: string,
): Note[] {
  const source = tracks.find((track) => track.id === setting.source);
  return (
    source?.clips.find((clip) => clip.section_id === sectionId)?.notes ?? []
  );
}
