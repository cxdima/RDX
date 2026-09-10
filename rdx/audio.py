from __future__ import annotations

import io
import json
import os
import subprocess
from pathlib import Path

import mido
import numpy as np
import soundfile as sf

from .domain import Note, Project


def decode_audio(source: Path, target: Path):
    result = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(source), "-t", "300", "-ar", "44100", "-ac", "2", str(target)], capture_output=True, timeout=60)
    if result.returncode:
        raise ValueError("This recording could not be decoded as audio")


def analysis(path: Path):
    audio, rate = sf.read(path, dtype="float32", always_2d=True)
    mono = audio.mean(axis=1)
    peak = float(np.max(np.abs(audio))) if len(audio) else 0
    rms = float(np.sqrt(np.mean(audio ** 2))) if len(audio) else 0
    bins = np.array_split(mono, 160)
    waveform = [round(float(np.max(np.abs(b))), 4) if len(b) else 0 for b in bins]
    return {"duration": len(audio) / rate, "peak_db": round(20 * np.log10(max(peak, 1e-8)), 1), "rms_db": round(20 * np.log10(max(rms, 1e-8)), 1), "waveform": waveform, "sample_rate": rate}


def transcribe(path: Path, tempo: float, bars: int, mode: str) -> list[Note]:
    os.environ.setdefault("NUMBA_CACHE_DIR", str(path.parent.parent / "numba-cache"))
    import librosa

    y, sr = librosa.load(path, sr=16000, mono=True, duration=30)
    if not len(y) or np.max(np.abs(y)) < 0.005:
        raise ValueError("The recording is silent or too quiet")
    beat_seconds = 60 / tempo
    onsets = librosa.onset.onset_detect(y=y, sr=sr, hop_length=256, units="time", backtrack=False)
    notes = []
    if mode == "rhythm":
        for onset in onsets:
            start = round(float(onset) / beat_seconds * 4) / 4
            if start < bars * 4:
                notes.append(Note(pitch=36, start=start, duration=min(0.12, bars * 4 - start), velocity=95))
    else:
        f0, voiced, probabilities = librosa.pyin(y, sr=sr, fmin=65, fmax=1100, frame_length=1024, hop_length=256)
        midi = np.full(len(f0), -1, dtype=int)
        usable = voiced & np.isfinite(f0) & (probabilities > 0.12)
        midi[usable] = np.rint(librosa.hz_to_midi(f0[usable])).astype(int)
        onset_frames = set(librosa.time_to_frames(onsets, sr=sr, hop_length=256).tolist())
        start = 0
        for index in range(1, len(midi) + 1):
            if index == len(midi) or midi[index] != midi[start] or index in onset_frames:
                seconds = (index - start) * 256 / sr
                if midi[start] >= 0 and seconds >= 0.07:
                    beat = round(start * 256 / sr / beat_seconds * 4) / 4
                    duration = max(0.125, round(seconds / beat_seconds * 4) / 4)
                    if beat < bars * 4:
                        notes.append(Note(pitch=int(midi[start]), start=beat, duration=min(duration, bars * 4 - beat), velocity=90))
                start = index
    unique = {(n.pitch, n.start): n for n in notes}
    if not unique:
        raise ValueError("No clear notes or beats were detected in this recording")
    return sorted(unique.values(), key=lambda n: n.start)


def midi_export(project: Project) -> bytes:
    midi = mido.MidiFile(ticks_per_beat=480)
    metadata = mido.MidiTrack()
    metadata.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(project.tempo)))
    metadata.append(mido.MetaMessage("time_signature", numerator=4, denominator=4))
    midi.tracks.append(metadata)
    offsets, position, previous_marker = {}, 0, 0
    for section in project.sections:
        offsets[section.id] = position
        metadata.append(mido.MetaMessage("marker", text=section.name, time=(position - previous_marker) * 480))
        previous_marker = position
        position += section.bars * 4
    for index, track in enumerate(project.tracks):
        channel = 9 if track.role == "drums" else [c for c in range(16) if c != 9][index % 15]
        midi_track = mido.MidiTrack()
        midi_track.append(mido.MetaMessage("track_name", name=track.name))
        events = []
        for clip in track.clips:
            offset = offsets[clip.section_id]
            for note in clip.notes:
                events.append((round((offset + note.start) * 480), 1, mido.Message("note_on", channel=channel, note=note.pitch, velocity=note.velocity)))
                events.append((round((offset + note.start + note.duration) * 480), 0, mido.Message("note_off", channel=channel, note=note.pitch, velocity=0)))
        last = 0
        for tick, _, message in sorted(events, key=lambda e: (e[0], e[1])):
            message.time = tick - last
            midi_track.append(message)
            last = tick
        midi.tracks.append(midi_track)
    buffer = io.BytesIO()
    midi.save(file=buffer)
    return buffer.getvalue()


def midi_import(data: bytes, bars: int):
    file = mido.MidiFile(file=io.BytesIO(data))
    output = []
    for index, track in enumerate(file.tracks):
        tick = 0
        pending, notes = {}, []
        name, drums = f"MIDI {index + 1}", False
        for msg in track:
            tick += msg.time
            if msg.type == "track_name":
                name = msg.name[:60]
            if msg.type == "note_on" and msg.velocity > 0:
                pending.setdefault((msg.channel, msg.note), []).append((tick, msg.velocity))
                drums |= msg.channel == 9
            elif msg.type in {"note_on", "note_off"}:
                stack = pending.get((msg.channel, msg.note), [])
                if stack:
                    start, velocity = stack.pop(0)
                    beat, duration = start / file.ticks_per_beat, (tick - start) / file.ticks_per_beat
                    if beat < bars * 4 and duration > 0:
                        notes.append(Note(pitch=msg.note, start=beat, duration=min(duration, bars * 4 - beat), velocity=velocity))
        if notes:
            output.append((name, "drums" if drums else "lead", notes))
    if not output:
        raise ValueError("No MIDI notes were found within the selected section's length")
    return output
