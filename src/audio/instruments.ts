import * as Tone from "tone";
import type { Sound } from "../types";

/**
 * Instrument voices. Each preset is a deliberate starting character rather
 * than an oscillator name — "strings" is a detuned ensemble with vibrato,
 * "supersaw" is the wide stacked lead trance is built on.
 */
export type Voice = {
  triggerNote(
    frequency: number,
    duration: number,
    time: number,
    velocity: number,
  ): void;
  nodes: { dispose(): unknown }[];
};

type Destination = Tone.InputNode;

const FAT = (
  type: "fatsawtooth" | "fatsine" | "fatsquare",
  count: number,
  spread: number,
) => ({ type, count, spread }) as Tone.OmniOscillatorOptions;

export function createVoice(sound: Sound, destination: Destination): Voice {
  const nodes: { dispose(): unknown }[] = [];
  const keep = <T extends { dispose(): unknown }>(node: T) => {
    nodes.push(node);
    return node;
  };
  const envelope = {
    attack: sound.attack,
    decay: sound.preset === "pluck" ? 0.18 : 0.3,
    sustain: sound.preset === "pluck" ? 0.12 : 0.6,
    release: sound.release,
  };

  // A riser or sweep: noise shaped by the track's filter and automation.
  if (sound.preset === "noise") {
    const synth = keep(
      new Tone.NoiseSynth({
        noise: { type: "pink" },
        envelope: {
          attack: sound.attack,
          decay: 0.1,
          sustain: 1,
          release: sound.release,
        },
        volume: -6,
      }).connect(destination),
    );
    return {
      nodes,
      triggerNote: (_frequency, duration, time, velocity) =>
        synth.triggerAttackRelease(duration, time, velocity),
    };
  }

  let target: Destination = destination;
  if (sound.preset === "strings" || sound.preset === "choir") {
    // Ensemble movement: a little pitch drift is what stops stacked saws
    // sounding like one synth holding a chord.
    target = keep(
      new Tone.Vibrato({
        frequency: sound.preset === "strings" ? 5.2 : 4.4,
        depth: sound.preset === "strings" ? 0.06 : 0.09,
      }).connect(destination),
    );
  }

  let synth: Tone.PolySynth;
  switch (sound.preset) {
    case "supersaw":
      synth = new Tone.PolySynth(Tone.Synth, {
        oscillator: FAT("fatsawtooth", 7, 40),
        envelope,
        volume: -12,
      });
      break;
    case "strings":
      synth = new Tone.PolySynth(Tone.Synth, {
        oscillator: FAT("fatsawtooth", 4, 22),
        envelope: { ...envelope, sustain: 0.85 },
        volume: -13,
      });
      break;
    case "choir":
      synth = new Tone.PolySynth(Tone.Synth, {
        oscillator: FAT("fatsine", 5, 45),
        envelope: { ...envelope, sustain: 0.9 },
        volume: -9,
      });
      break;
    case "pad":
      synth = new Tone.PolySynth(Tone.Synth, {
        oscillator: FAT("fatsawtooth", 3, 30),
        envelope: { ...envelope, sustain: 0.8 },
        volume: -13,
      });
      break;
    case "sub":
      synth = new Tone.PolySynth(Tone.Synth, {
        oscillator: { type: "sine" } as Tone.OmniOscillatorOptions,
        envelope: { ...envelope, sustain: 0.9 },
        volume: -4,
      });
      break;
    case "bell":
      synth = new Tone.PolySynth(Tone.FMSynth, {
        harmonicity: 3.01,
        modulationIndex: 14,
        envelope: { ...envelope, sustain: 0 },
        modulationEnvelope: {
          attack: 0.001,
          decay: 0.35,
          sustain: 0,
          release: 0.2,
        },
        volume: -12,
      });
      break;
    case "fm":
      synth = new Tone.PolySynth(Tone.FMSynth, {
        harmonicity: 2,
        modulationIndex: 8,
        envelope,
        volume: -11,
      });
      break;
    case "sine":
      synth = new Tone.PolySynth(Tone.Synth, {
        oscillator: { type: "sine" } as Tone.OmniOscillatorOptions,
        envelope,
        volume: -8,
      });
      break;
    case "pluck":
      synth = new Tone.PolySynth(Tone.Synth, {
        oscillator: { type: "triangle" } as Tone.OmniOscillatorOptions,
        envelope,
        volume: -8,
      });
      break;
    default:
      synth = new Tone.PolySynth(Tone.Synth, {
        oscillator: { type: "sawtooth" } as Tone.OmniOscillatorOptions,
        envelope,
        volume: -10,
      });
  }
  synth.maxPolyphony = 32;
  if (sound.glide > 0) synth.set({ portamento: sound.glide });
  keep(synth.connect(target));

  return {
    nodes,
    triggerNote: (frequency, duration, time, velocity) =>
      synth.triggerAttackRelease(frequency, duration, time, velocity),
  };
}
