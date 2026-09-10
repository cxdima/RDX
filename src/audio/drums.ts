import * as Tone from "tone";

/**
 * The drum pitches RDX plays. This mirrors DRUM_MAP in rdx/domain.py and
 * tests/test_musical.py asserts the two stay identical, so a pattern written
 * in Python always reaches the voice it was written for.
 */
export const DRUM_MAP: Record<number, string> = {
  36: "Kick",
  37: "Rim",
  38: "Snare",
  39: "Clap",
  42: "Hat",
  44: "Pedal",
  45: "Low tom",
  46: "Open",
  47: "Mid tom",
  49: "Crash",
  50: "High tom",
  51: "Ride",
};

export type DrumKit = {
  trigger(pitch: number, time: number, velocity: number): void;
  nodes: { dispose(): unknown }[];
};

type Destination = Tone.InputNode;

/** A noise burst through a band of the spectrum — the basis of most of a kit. */
function noiseVoice(
  destination: Destination,
  filter: Tone.FilterOptions["type"],
  frequency: number,
  decay: number,
  volume: number,
  Q = 1,
) {
  const shape = new Tone.Filter({ type: filter, frequency, Q }).connect(
    destination,
  );
  const synth = new Tone.NoiseSynth({
    noise: { type: "white" },
    envelope: { attack: 0.001, decay, sustain: 0 },
    volume,
  }).connect(shape);
  return { synth, nodes: [synth, shape] };
}

export function createKit(destination: Destination): DrumKit {
  const nodes: { dispose(): unknown }[] = [];
  const keep = <T extends { dispose(): unknown }>(node: T) => {
    nodes.push(node);
    return node;
  };

  const kick = keep(
    new Tone.MembraneSynth({
      pitchDecay: 0.035,
      octaves: 7,
      envelope: { attack: 0.001, decay: 0.3, sustain: 0, release: 0.1 },
      volume: -2,
    }).connect(destination),
  );
  const toms = keep(
    new Tone.MembraneSynth({
      pitchDecay: 0.02,
      octaves: 3,
      envelope: { attack: 0.001, decay: 0.25, sustain: 0, release: 0.1 },
      volume: -8,
    }).connect(destination),
  );

  const snareNoise = noiseVoice(destination, "highpass", 1400, 0.13, -12);
  const snareBody = keep(
    new Tone.MembraneSynth({
      pitchDecay: 0.01,
      octaves: 2,
      envelope: { attack: 0.001, decay: 0.11, sustain: 0 },
      volume: -18,
    }).connect(destination),
  );
  snareNoise.nodes.forEach(keep);

  // A clap is several very short bursts a few milliseconds apart, then a
  // slightly longer tail. That stagger is what makes it read as hands.
  const clap = noiseVoice(destination, "bandpass", 1250, 0.09, -10, 1.6);
  clap.nodes.forEach(keep);

  const hat = noiseVoice(destination, "highpass", 8500, 0.035, -17);
  const pedal = noiseVoice(destination, "highpass", 7000, 0.022, -20);
  const open = noiseVoice(destination, "highpass", 7800, 0.32, -19);
  const crash = noiseVoice(destination, "highpass", 4200, 1.6, -16);
  const ride = noiseVoice(destination, "bandpass", 5200, 0.5, -21, 0.8);
  const rim = noiseVoice(destination, "bandpass", 2200, 0.03, -14, 3);
  [hat, pedal, open, crash, ride, rim].forEach((voice) =>
    voice.nodes.forEach(keep),
  );

  const CLAP_SPREAD = [0, 0.009, 0.019, 0.031];

  return {
    nodes,
    trigger(pitch, time, velocity) {
      switch (pitch) {
        case 36:
          kick.triggerAttackRelease("C1", 0.12, time, velocity);
          return;
        case 38:
          snareNoise.synth.triggerAttackRelease(0.11, time, velocity);
          snareBody.triggerAttackRelease("G2", 0.08, time, velocity * 0.8);
          return;
        case 39:
          for (const offset of CLAP_SPREAD)
            clap.synth.triggerAttackRelease(
              offset === CLAP_SPREAD[CLAP_SPREAD.length - 1] ? 0.09 : 0.02,
              time + offset,
              velocity * (offset ? 0.7 : 1),
            );
          return;
        case 37:
          rim.synth.triggerAttackRelease(0.03, time, velocity);
          return;
        case 42:
          hat.synth.triggerAttackRelease(0.035, time, velocity);
          return;
        case 44:
          pedal.synth.triggerAttackRelease(0.022, time, velocity);
          return;
        case 46:
          open.synth.triggerAttackRelease(0.3, time, velocity);
          return;
        case 49:
          crash.synth.triggerAttackRelease(1.4, time, velocity);
          return;
        case 51:
          ride.synth.triggerAttackRelease(0.45, time, velocity);
          return;
        case 45:
          toms.triggerAttackRelease("A1", 0.22, time, velocity);
          return;
        case 47:
          toms.triggerAttackRelease("D2", 0.2, time, velocity);
          return;
        case 50:
          toms.triggerAttackRelease("A2", 0.18, time, velocity);
          return;
        default:
          hat.synth.triggerAttackRelease(0.035, time, velocity);
      }
    },
  };
}
