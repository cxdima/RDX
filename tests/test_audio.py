import io

import mido
import numpy as np
import pytest
import soundfile as sf

from rdx.audio import analysis, midi_export, midi_import, transcribe
from rdx.engine import starter_project


def test_midi_notes_and_section_markers_round_trip():
    project = starter_project()
    contents = midi_export(project)
    file = mido.MidiFile(file=io.BytesIO(contents))
    tick = 0
    markers = []
    for message in file.tracks[0]:
        tick += message.time
        if message.type == "marker":
            markers.append((message.text, tick / file.ticks_per_beat))
    assert markers == [("Intro", 0), ("Build", 16), ("Main", 32), ("Outro", 64)]
    imported = midi_import(contents, 20)
    assert sum(len(notes) for _, _, notes in imported) == sum(len(c.notes) for t in project.tracks for c in t.clips)
    assert imported[0][1] == "drums"


def test_monophonic_transcription_and_measurements(tmp_path):
    rate = 16000
    time = np.arange(rate * 2) / rate
    signal = .25 * np.sin(2 * np.pi * 440 * time)
    signal[:1600] = 0
    signal[-1600:] = 0
    path = tmp_path / "tone.wav"
    sf.write(path, signal, rate)
    info = analysis(path)
    assert info["duration"] == 2
    assert len(info["waveform"]) == 160
    assert -13 < info["peak_db"] < -11
    notes = transcribe(path, 120, 4, "hum")
    assert sum(n.duration for n in notes if n.pitch == 69) > 2
    sf.write(path, np.zeros(rate), rate)
    with pytest.raises(ValueError, match="silent"):
        transcribe(path, 120, 4, "hum")
