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
    drive?: Automatable;
    width?: Automatable;
    delay?: Automatable;
    crush?: Automatable;
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

  let driveParam: Automatable | undefined;
  if (used("drive")) {
    const distortion = keep(
      new Tone.Distortion({
        distortion: Math.max(sound.drive, 0.4),
        wet: sound.drive > 0 ? 0.4 : 0,
      }),
    );
    driveParam = distortion.wet;
    stages.push(distortion);
  }

  // Bit reduction: 16 bits is transparent, 2 is destroyed, and the control
  // runs the other way round so that "more crush" means more of it.
  let crushParam: Automatable | undefined;
  if (used("crush")) {
    const crusher = keep(
      new Tone.BitCrusher(
        Math.max(1, Math.round(16 - Math.max(sound.crush, 0.5) * 14)),
      ),
    );
    crusher.wet.value = Math.min(
      1,
      sound.crush > 0 ? 0.35 + sound.crush * 0.65 : 0,
    );
    crushParam = crusher.wet;
    stages.push(crusher);
  }

  // The dedicated LFO, with one named destination. Pitch and volume are done
  // with Tone's own vibrato and tremolo because they are the same thing done
  // properly; cutoff is wired straight to the filter this chain already has.
  if (sound.lfo_target === "pitch" && sound.lfo_depth > 0)
    stages.push(
      keep(
        new Tone.Vibrato({
          frequency: sound.lfo_rate,
          depth: sound.lfo_depth * 0.3,
        }),
      ),
    );
  if (sound.lfo_target === "volume" && sound.lfo_depth > 0)
    stages.push(
      keep(
        new Tone.Tremolo({
          frequency: sound.lfo_rate,
          depth: sound.lfo_depth,
          spread: 0,
        }).start(),
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

  let widthParam: Automatable | undefined;
  if (used("width")) {
    const widener = keep(
      new Tone.StereoWidener({ width: 0.5 + sound.width * 0.5 }),
    );
    widthParam = widener.width;
    stages.push(widener);
  }

  let delayParam: Automatable | undefined;
  if (used("delay")) {
    const echo = keep(
      new Tone.FeedbackDelay({
        delayTime: secondsPerBeat * 0.75,
        feedback: 0.25,
        wet: sound.delay,
      }),
    );
    delayParam = echo.wet;
    stages.push(echo);
  }

  let reverbParam: Automatable | undefined;
  let reverbSend: Tone.Gain | undefined;
  if (used("reverb")) {
    // A send, not an insert, and high-passed before the reverb. Reverb is
    // essential to trance and it clogs a mix without EQ — a producer's
    // words — because a reverb tail on a bass or a low pad smears the very
    // band the kick needs clear. The dry signal passes untouched; only the
    // part above 300 Hz reverberates, and the send level is what automation
    // and the reverb control drive.
    reverbSend = keep(new Tone.Gain(sound.reverb));
    const above = keep(
      new Tone.Filter({ type: "highpass", frequency: 300, Q: 0.7 }),
    );
    const reverb = keep(new Tone.Reverb({ decay: 1.6, wet: 1 }));
    reverbSend.chain(above, reverb, destination);
    reverbParam = reverbSend.gain;
  }

  // Sweeping the filter itself, around the cutoff rather than from zero, so a
  // deep wobble still passes the body of the sound.
  if (
    sound.lfo_target === "cutoff" &&
    sound.lfo_depth > 0 &&
    !animated.has("cutoff")
  ) {
    const span = sound.cutoff * 0.9 * sound.lfo_depth;
    const sweep = keep(
      new Tone.LFO({
        frequency: sound.lfo_rate,
        min: Math.max(60, sound.cutoff - span),
        max: Math.min(20000, sound.cutoff + span * 0.6),
      }).start(),
    );
    sweep.connect(filter.frequency);
  }

  filter.chain(...stages, destination);
  // The reverb send taps the end of the chain, so chorus and echo go into the
  // room too, and sums back into the same destination beside the dry path.
  if (reverbSend) (stages[stages.length - 1] ?? filter).connect(reverbSend);
  return {
    input: filter,
    params: {
      cutoff: filter.frequency,
      resonance: filter.Q,
      reverb: reverbParam,
      flanger: flangerParam,
      chorus: chorusParam,
      drive: driveParam,
      width: widthParam,
      delay: delayParam,
      crush: crushParam,
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
