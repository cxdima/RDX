from __future__ import annotations

from rdx.domain import Action, Clip, new_track
from rdx.engine import apply_actions, starter_project
from rdx.musical.describe import describe


def test_revising_existing_automation_is_not_reported_as_nothing():
    before = apply_actions(starter_project(), [Action(kind="automation", track="lead", section="Main", params={
        "parameter": "cutoff", "points": [[0, 400], [32, 9000]],
    })])
    after = apply_actions(before, [Action(kind="automation", track="lead", section="Main", params={
        "parameter": "cutoff", "points": [[0, 9000], [32, 400]],
    })])
    assert "filter automation changed in Main" in describe(before, after)


def test_recording_offsets_are_real_edits_even_without_midi_notes():
    before = starter_project()
    audio = new_track("audio", "Vocal")
    audio.clips = [Clip(section_id=before.sections[2].id, audio_id="123456789abc")]
    before.tracks.append(audio)
    after = apply_actions(before, [Action(kind="notes", track=audio.id, section="Main", params={
        "operation": "audio_offset", "audio_offset": 1.5,
    })])
    assert "recording start in Main 0 to 1.5 s" in describe(before, after)


def test_renaming_and_resizing_do_not_hide_each_other_or_use_the_old_name():
    before = starter_project()
    after = apply_actions(before, [
        Action(kind="arrange", section="Main", params={"operation": "update", "bars": 4, "name": "Drop", "energy": 0.8}),
        Action(kind="transpose", track="lead", section="Drop", params={"semitones": 12}),
    ])
    told = describe(before, after)
    assert "Drop: 8 to 4 bars" in told
    assert "Section Main renamed to Drop" in told
    assert "Drop energy 1 to 0.8" in told
    assert "Main notes changed" not in told


def test_condensed_removals_still_name_where_material_was_lost():
    before = starter_project()
    after = before.model_copy(deep=True)
    after.tracks[0].clips = []
    told = describe(before, after)
    assert "parts removed from 4 sections" in told
    assert all(s.name in told for s in before.sections)
