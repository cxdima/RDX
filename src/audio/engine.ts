import * as Tone from "tone";
import type { Project } from "../types";
import { createKit } from "./drums";
import { createChain, ready } from "./effects";
import { createVoice } from "./instruments";
import { duckingPoints, sourceNotes, triggerBeats } from "./sidechain";

type Disposable = { dispose(): unknown };

export class StudioAudio {
  private nodes: Disposable[] = [];
  private channels = new Map<string, Tone.Channel>();
  private meters = new Map<string, Tone.Meter>();
  private generation = 0;
  private master?: Tone.Volume;
  private outputMeter?: Tone.Meter;

  dispose() {
    this.generation++;
    Tone.getTransport().stop();
    Tone.getTransport().cancel();
    for (const node of this.nodes.reverse()) node.dispose();
    this.nodes = [];
    this.channels.clear();
    this.meters.clear();
    this.master = undefined;
    this.outputMeter = undefined;
  }

  get seconds() {
    return Tone.getTransport().seconds;
  }
  get playing() {
    return Tone.getTransport().state === "started";
  }
  meter(id: string) {
    const value = (
      id === "master" ? this.outputMeter : this.meters.get(id)
    )?.getValue();
    return typeof value === "number" ? value : -100;
  }

  updateMix(project: Project) {
    const solo = project.tracks.some((t) => t.solo);
    project.tracks.forEach((track) => {
      const channel = this.channels.get(track.id);
      if (channel) {
        channel.volume.rampTo(track.volume_db, 0.03);
        channel.pan.rampTo(track.pan, 0.03);
        channel.mute = track.mute || (solo && !track.solo);
      }
    });
    this.master?.volume.rampTo(project.master.volume_db, 0.03);
  }

  async build(project: Project) {
    const generation = this.generation;
    const transport = Tone.getTransport();
    const secondsPerBeat = 60 / project.tempo;
    transport.bpm.value = project.tempo;
    const output = new Tone.Volume(project.master.volume_db);
    const compressor = new Tone.Compressor(project.master.compression, 2);
    const limiter = new Tone.Limiter(project.master.ceiling);
    const meter = new Tone.Meter({ smoothing: 0.7 });
    output.chain(compressor, limiter, meter, Tone.getDestination());
    this.master = output;
    this.outputMeter = meter;
    this.nodes.push(output, compressor, limiter, meter);

    let offset = 0;
    const offsets = new Map<string, number>();
    for (const section of project.sections) {
      offsets.set(section.id, offset);
      offset += section.bars * 4;
    }
    const solo = project.tracks.some((t) => t.solo);

    for (const track of project.tracks) {
      const channel = new Tone.Channel({
        volume: track.volume_db,
        pan: track.pan,
        mute: track.mute || (solo && !track.solo),
      }).connect(output);
      const trackMeter = new Tone.Meter({ smoothing: 0.75 });
      channel.connect(trackMeter);
      this.nodes.push(channel, trackMeter);
      this.channels.set(track.id, channel);
      this.meters.set(track.id, trackMeter);

      // Ducking sits before the channel so it multiplies the fader rather
      // than fighting a volume automation lane for the same parameter.
      const duck = track.sidechain
        ? new Tone.Gain(1).connect(channel)
        : undefined;
      if (duck) this.nodes.push(duck);

      const animated = new Set(track.automation.map((lane) => lane.parameter));
      const chain = createChain(
        track.sound,
        duck ?? channel,
        animated,
        secondsPerBeat,
      );
      this.nodes.push(...chain.nodes);
      await ready(chain);
      if (generation !== this.generation) return;

      const kit =
        track.role === "drums"
          ? createKit(chain.input, track.kit ?? undefined)
          : null;
      const voice =
        track.role === "drums" || track.role === "audio"
          ? null
          : createVoice(track.sound, chain.input);
      if (kit) this.nodes.push(...kit.nodes);
      if (voice) this.nodes.push(...voice.nodes);

      for (const clip of track.clips) {
        const clipOffset = offsets.get(clip.section_id) || 0;
        if (clip.audio_id) {
          const player = new Tone.Player({
            url: `/api/audio/${clip.audio_id}/wave`,
            fadeIn: 0.01,
            fadeOut: 0.02,
          }).connect(chain.input);
          this.nodes.push(player);
          await Tone.loaded();
          if (generation !== this.generation) return;
          const section = project.sections.find(
            (s) => s.id === clip.section_id,
          )!;
          transport.schedule((time) => {
            const duration = Math.min(
              section.bars * 4 * secondsPerBeat,
              player.buffer.duration - clip.audio_offset,
            );
            if (duration > 0) player.start(time, clip.audio_offset, duration);
          }, clipOffset * secondsPerBeat);
        }
        for (const note of clip.notes) {
          transport.schedule(
            (time) => {
              const velocity = note.velocity / 127;
              if (kit) kit.trigger(note.pitch, time, velocity);
              else
                voice?.triggerNote(
                  Tone.Frequency(note.pitch, "midi").toFrequency(),
                  note.duration * secondsPerBeat,
                  time,
                  velocity,
                );
            },
            (clipOffset + note.start) * secondsPerBeat,
          );
        }
      }

      if (duck && track.sidechain) {
        const setting = track.sidechain;
        for (const section of project.sections) {
          const beats = triggerBeats(
            sourceNotes(setting, project.tracks, section.id),
            setting.trigger,
          );
          const points = duckingPoints(beats, section.bars * 4, setting);
          transport.schedule(
            (time) => {
              duck.gain.cancelScheduledValues(time);
              points.forEach(([beat, gain], index) => {
                const at = time + beat * secondsPerBeat;
                if (index === 0) duck.gain.setValueAtTime(gain, at);
                else duck.gain.linearRampToValueAtTime(gain, at);
              });
            },
            (offsets.get(section.id) || 0) * secondsPerBeat,
          );
        }
      }

      for (const lane of track.automation) {
        // Every automatable name in rdx/domain.py has to land on a real signal
        // here; a test asserts the two lists stay the same length.
        const parameter =
          lane.parameter === "volume_db"
            ? channel.volume
            : lane.parameter === "pan"
              ? channel.pan
              : chain.params[lane.parameter as keyof typeof chain.params];
        if (!parameter) continue;
        transport.schedule(
          (time) => {
            parameter.cancelScheduledValues(time);
            lane.points.forEach(([beat, value], index) => {
              if (index === 0)
                parameter.setValueAtTime(value, time + beat * secondsPerBeat);
              else
                parameter.linearRampToValueAtTime(
                  value,
                  time + beat * secondsPerBeat,
                );
            });
          },
          (offsets.get(lane.section_id) || 0) * secondsPerBeat,
        );
      }
    }
  }

  async play(project: Project, sectionId: string, loop: boolean) {
    await Tone.start();
    this.dispose();
    const generation = this.generation;
    await this.build(project);
    if (generation !== this.generation) return;
    let start = 0;
    for (const section of project.sections) {
      if (section.id === sectionId) break;
      start += section.bars * 4;
    }
    const section = project.sections.find((s) => s.id === sectionId)!;
    const duration =
      (project.sections.reduce((sum, s) => sum + s.bars * 4, 0) * 60) /
      project.tempo;
    const transport = Tone.getTransport();
    transport.loop = loop;
    transport.loopStart = (start * 60) / project.tempo;
    transport.loopEnd = ((start + section.bars * 4) * 60) / project.tempo;
    if (!loop)
      transport.scheduleOnce(() => {
        transport.stop();
      }, duration);
    transport.start("+0.08", loop ? (start * 60) / project.tempo : 0);
  }

  stop() {
    this.dispose();
  }

  async render(project: Project): Promise<Blob> {
    this.stop();
    const seconds =
      (project.sections.reduce((sum, section) => sum + section.bars * 4, 0) *
        60) /
        project.tempo +
      3;
    const renderer = new StudioAudio();
    const buffer = await Tone.Offline(
      async ({ transport }) => {
        await renderer.build(project);
        transport.loop = false;
        transport.start(0);
      },
      seconds,
      2,
      44100,
    );
    const channels = [buffer.getChannelData(0), buffer.getChannelData(1)];
    const bytes = new ArrayBuffer(44 + channels[0].length * 4);
    const view = new DataView(bytes);
    const text = (offset: number, value: string) =>
      [...value].forEach((c, i) => view.setUint8(offset + i, c.charCodeAt(0)));
    text(0, "RIFF");
    view.setUint32(4, bytes.byteLength - 8, true);
    text(8, "WAVE");
    text(12, "fmt ");
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);
    view.setUint16(22, 2, true);
    view.setUint32(24, 44100, true);
    view.setUint32(28, 176400, true);
    view.setUint16(32, 4, true);
    view.setUint16(34, 16, true);
    text(36, "data");
    view.setUint32(40, bytes.byteLength - 44, true);
    for (let i = 0; i < channels[0].length; i++)
      for (let c = 0; c < 2; c++)
        view.setInt16(
          44 + i * 4 + c * 2,
          Math.max(-1, Math.min(1, channels[c][i])) * 32767,
          true,
        );
    for (const node of renderer.nodes.reverse()) node.dispose();
    return new Blob([bytes], { type: "audio/wav" });
  }
}

export const studioAudio = new StudioAudio();
