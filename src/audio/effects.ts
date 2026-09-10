import * as Tone from "tone";
import type { Sound } from "../types";

/** The three scheduling methods automation needs, shared by Param and Signal. */
export type Automatable = {
  cancelScheduledValues(time: Tone.Unit.Time): unknown;
  setValueAtTime(value: number, time: Tone.Unit.Time): unknown;
  linearRampToValueAtTime(value: number, time: Tone.Unit.Time): unknown;
};

export type Chain = {
  input: Tone.InputNode;
  params: {
    cutoff: Automatable;
    resonance: Automatable;
    reverb?: Automatable;
    flanger?: Automatable;
    chorus?: Automatable;
  };
  nodes: { dispose(): unknown }[];
};

/**
 * The processing chain for one track, in the order a producer would patch it:
 * filter, tone, drive, then movement, then space.
 *
 * Effects that are off and not being automated are not created at all, so an
 * arrangement only pays for the sound it actually uses.
 */
export function createChain(
  sound: Sound,
  destination: Tone.InputNode,
  animated: ReadonlySet<string>,
  secondsPerBeat: number,
): Chain {
  const nodes: { dispose(): unknown }[] = [];
  const keep = <T extends { dispose(): unknown }>(node: T) => {
    nodes.push(node);
    return node;
  };
  const used = (name: keyof Sound) =>
    Number(sound[name]) > 0 || animated.has(name);

  const filter = keep(
    new Tone.Filter({
      frequency: sound.cutoff,
      Q: sound.resonance,
      type: "lowpass",
    }),
  );
  const eq = keep(new Tone.EQ3(sound.low, sound.mid, sound.high));
  const stages: Tone.ToneAudioNode[] = [eq];

  if (used("drive"))
    stages.push(
      keep(
        new Tone.Distortion({
          distortion: sound.drive,
          wet: sound.drive > 0 ? 0.4 : 0,
        }),
      ),
    );

  let chorusParam: Automatable | undefined;
  if (used("chorus")) {
    const chorus = keep(
      new Tone.Chorus({
        frequency: Math.min(8, sound.motion_rate * 3),
        delayTime: 3.5,
        depth: 0.7,
        wet: sound.chorus,
      }).start(),
    );
    chorusParam = chorus.wet;
    stages.push(chorus);
  }

  let flangerParam: Automatable | undefined;
  if (used("flanger")) {
    // Tone has no flanger, so this is the real thing: a very short delay whose
    // time is swept by an LFO, fed back on itself.
    const flanger = keep(
      new Tone.FeedbackDelay({
        delayTime: 0.005,
        feedback: 0.55,
        maxDelay: 0.02,
        wet: sound.flanger,
      }),
    );
    const sweep = keep(
      new Tone.LFO({
        frequency: sound.motion_rate,
        min: 0.0012,
        max: 0.0085,
      }).start(),
    );
    sweep.connect(flanger.delayTime);
    flangerParam = flanger.wet;
    stages.push(flanger);
  }

  if (used("phaser"))
    stages.push(
      keep(
        new Tone.Phaser({
          frequency: sound.motion_rate,
          octaves: 4,
          baseFrequency: 400,
          wet: sound.phaser,
        }),
      ),
    );

  if (used("autopan"))
    stages.push(
      keep(
        new Tone.AutoPanner({
          frequency: sound.motion_rate,
          depth: sound.autopan,
          wet: 1,
        }).start(),
      ),
    );

  if (used("width"))
    stages.push(
      keep(new Tone.StereoWidener({ width: 0.5 + sound.width * 0.5 })),
    );

  if (used("delay"))
    stages.push(
      keep(
        new Tone.FeedbackDelay({
          delayTime: secondsPerBeat * 0.75,
          feedback: 0.25,
          wet: sound.delay,
        }),
      ),
    );

  let reverbParam: Automatable | undefined;
  if (used("reverb")) {
    const reverb = keep(new Tone.Reverb({ decay: 1.6, wet: sound.reverb }));
    reverbParam = reverb.wet;
    stages.push(reverb);
  }

  filter.chain(...stages, destination);
  return {
    input: filter,
    params: {
      cutoff: filter.frequency,
      resonance: filter.Q,
      reverb: reverbParam,
      flanger: flangerParam,
      chorus: chorusParam,
    },
    nodes,
  };
}

/** Reverb impulse responses generate asynchronously; wait before scheduling. */
export async function ready(chain: Chain) {
  await Promise.all(
    chain.nodes.map((node) =>
      node instanceof Tone.Reverb ? node.ready : Promise.resolve(),
    ),
  );
}
