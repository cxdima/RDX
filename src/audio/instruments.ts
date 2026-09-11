import * as Tone from "tone";
import type { Sound } from "../types";

/**
 * Instrument voices. Each preset is a deliberate starting character rather
 * than an oscillator name — "strings" is a detuned ensemble with vibrato,
 * "supersaw" is the wide stacked lead trance is built on.
 *
 * The synth controls themselves live in the Sound model: a full ADSR, a filter
 * envelope, unison and spread, a sub oscillator and an octave. A preset now
 * chooses where those start (see PRESET_DEFAULTS in rdx/domain.py) rather than
 * hard-coding them here, so "shorten the decay" is a real request on any sound.
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

/** The oscillator for a preset, widened into unison when the sound asks. */
function oscillator(sound: Sound): Tone.OmniOscillatorOptions {
  const shapes: Record<string, string> = {
    saw: "sawtooth",
    square: "square",
    triangle: "triangle",
    sine: "sine",
    pulse: "pulse",
  };
  const byPreset: Record<string, string> = {
    supersaw: "sawtooth",
    saw: "sawtooth",
    strings: "sawtooth",
    pad: "sawtooth",
    choir: "sine",
    sub: "sine",
    sine: "sine",
    pluck: "triangle",
  };
  // An unknown wave falls back to the preset's own rather than taking the
  // whole audio engine down with it.
  const base = shapes[sound.wave] ?? byPreset[sound.preset] ?? "sawtooth";
  if (sound.unison > 1 && base !== "pulse")
    return {
      type: `fat${base}`,
      count: sound.unison,
      spread: sound.spread,
    } as unknown as Tone.OmniOscillatorOptions;
  return { type: base } as unknown as Tone.OmniOscillatorOptions;
}

// Measured on a rendered trance drop, each part alone: drums -23 LUFS, bass
// -22, chords -40, lead -40. Seventeen decibels between the rhythm section and
// the melody is not a balance, it is a record you cannot hear the tune of. The
// sustained presets were the quiet ones; the master chain now does the
// loudness, so they can sit where a mix needs them.
const PRESET_VOLUME: Record<string, number> = {
  supersaw: -6,
  strings: -7,
  choir: -6,
  pad: -7,
  // Was -4, six to nine dB above every other preset. A rendered trance drop
  // measured its 40-80 Hz band thirty decibels above everything past 320 Hz —
  // not bass-heavy, only bass — and the same hot sub was what overshot the
  // limiter. In line with the rest, the master chain does the loudness.
  sub: -10,
  bell: -12,
  fm: -11,
  sine: -8,
  pluck: -8,
  saw: -10,
};

/** Where a voice's fader sits before the track and master do their part.
 *
 * Tone scales every unison voice to -6 - count * 1.1 dB. Seven of them summing
 * incoherently give back about +8.5, so a supersaw lands 5 dB *quieter* than
 * one plain saw — the opposite of what unison is for, and measured on a rendered
 * drop as a lead 10 dB under the kick. The 5 dB is given back here, in the one
 * place both synth paths read from, because it hid for a night in a branch the
 * supersaw never took. */
function voiceVolume(sound: Sound): number {
  return (PRESET_VOLUME[sound.preset] ?? -10) + (sound.unison > 1 ? 5 : 0);
}

export function createVoice(sound: Sound, destination: Destination): Voice {
  const nodes: { dispose(): unknown }[] = [];
  const keep = <T extends { dispose(): unknown }>(node: T) => {
    nodes.push(node);
    return node;
  };
  const envelope = {
    attack: sound.attack,
    decay: sound.decay,
    sustain: sound.sustain,
    release: sound.release,
  };
  const shift = 2 ** sound.octave;

  // A riser or sweep: noise shaped by the track's filter and automation.
  if (sound.preset === "noise") {
    const synth = keep(
      new Tone.NoiseSynth({
        noise: { type: "pink" },
        envelope,
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

  // A sub oscillator is its own voice an octave down, mixed in underneath.
  let subVoice: Tone.PolySynth | undefined;
  if (sound.sub > 0) {
    const gain = keep(new Tone.Gain(sound.sub).connect(target));
    subVoice = keep(
      new Tone.PolySynth(Tone.Synth, {
        oscillator: { type: "sine" } as Tone.OmniOscillatorOptions,
        envelope,
        volume: -6,
      }).connect(gain),
    );
    subVoice.maxPolyphony = 16;
  }

  let synth: Tone.PolySynth;
  if (sound.filter_env !== 0) {
    // A filter envelope has to be per voice, so the note that opened the
    // filter is the note that closes it. MonoSynth is Tone's voice that has
    // one; PolySynth makes it polyphonic.
    const octaves = Math.max(-4, Math.min(4, sound.filter_env * 4));
    synth = new Tone.PolySynth(Tone.MonoSynth, {
      oscillator: oscillator(sound),
      envelope,
      filter: {
        type: "lowpass",
        Q: Math.min(15, sound.resonance),
        rolloff: -24,
      },
      filterEnvelope: {
        attack: 0.002,
        decay: sound.filter_decay,
        sustain: 0,
        release: sound.filter_decay,
        baseFrequency: Math.max(60, sound.cutoff * 0.35),
        octaves,
        exponent: 2,
      },
      // A resonant filter per voice runs hot; two decibels keeps it in line.
      volume: voiceVolume(sound) - 2,
    });
  } else {
    switch (sound.preset) {
      case "bell":
        synth = new Tone.PolySynth(Tone.FMSynth, {
          harmonicity: 3.01,
          modulationIndex: 14,
          envelope,
          modulationEnvelope: {
            attack: 0.001,
            decay: 0.35,
            sustain: 0,
            release: 0.2,
          },
          volume: PRESET_VOLUME.bell,
        });
        break;
      case "fm":
        synth = new Tone.PolySynth(Tone.FMSynth, {
          harmonicity: 2,
          modulationIndex: 8,
          envelope,
          volume: PRESET_VOLUME.fm,
        });
        break;
      default:
        synth = new Tone.PolySynth(Tone.Synth, {
          oscillator: oscillator(sound),
          envelope,
          volume: voiceVolume(sound),
        });
    }
  }
  synth.maxPolyphony = 32;
  if (sound.glide > 0) synth.set({ portamento: sound.glide });
  keep(synth.connect(target));

  return {
    nodes,
    triggerNote: (frequency, duration, time, velocity) => {
      synth.triggerAttackRelease(frequency * shift, duration, time, velocity);
      subVoice?.triggerAttackRelease(
        frequency * shift * 0.5,
        duration,
        time,
        velocity,
      );
    },
  };
}
