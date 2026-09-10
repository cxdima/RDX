import pytest

from rdx.domain import Action, Note, Project
from rdx.engine import apply_actions, starter_project


@pytest.fixture
def project():
    return starter_project()


def action(kind, params, project, track="lead", section="Main"):
    return Action(kind=kind, params=params, track=next(t.id for t in project.tracks if t.role == track), section=next(s.id for s in project.sections if s.name == section))


def test_atomic_failure_leaves_original_untouched(project):
    original = project.model_dump()
    edits = [action("mix", {"delta_db": -2}, project), action("transpose", {"semitones": 999}, project)]
    with pytest.raises(ValueError):
        apply_actions(project, edits)
    assert original == project.model_dump()


def test_last_note_preserves_everything_else(project):
    track = project.tracks[-1]
    clip = next(c for c in track.clips if c.section_id == project.sections[2].id)
    target = max(clip.notes, key=lambda n: n.start)
    updated = apply_actions(project, [action("transpose", {"semitones": 2, "last_note": True}, project)])
    expected = project.model_copy(deep=True)
    for c in expected.tracks[-1].clips:
        for n in c.notes:
            if n.id == target.id:
                n.pitch += 2
    assert updated == expected


def test_protection_and_all_target(project):
    project.tracks[0].locked = True
    with pytest.raises(ValueError, match="protected"):
        apply_actions(project, [action("mix", {"delta_db": -2}, project, "drums")])
    result = apply_actions(project, [Action(kind="mix", track="all", params={"delta_db": -2})])
    assert result.tracks[0] == project.tracks[0]
    assert all(a.volume_db == b.volume_db - 2 for a, b in zip(result.tracks[1:], project.tracks[1:]))


def test_duplicate_has_independent_notes_and_automation(project):
    result = apply_actions(project, [action("automation", {"parameter":"cutoff", "points":[[0, 400], [32, 9000]]}, project), action("arrange", {"operation":"duplicate"}, project)])
    assert result.sections[3].name == "Main 2"
    assert result.sections[3].id != project.sections[2].id
    lead = result.tracks[-1]
    old = next(c for c in lead.clips if c.section_id == project.sections[2].id)
    new = next(c for c in lead.clips if c.section_id == result.sections[3].id)
    assert [n.pitch for n in old.notes] == [n.pitch for n in new.notes]
    assert {n.id for n in old.notes}.isdisjoint(n.id for n in new.notes)
    assert len(lead.automation) == 2


@pytest.mark.parametrize("params", [{"delta_db": "quiet"}, {"volume_db": float("nan")}, {"mute": "false"}, {"volume_db": 7}, {"unknown": 2}])
def test_invalid_parameters_are_rejected(project, params):
    with pytest.raises(ValueError):
        apply_actions(project, [action("mix", params, project)])


def test_notes_can_create_empty_clip(project):
    result = apply_actions(project, [action("notes", {"notes":[{"pitch":69,"start":0,"duration":1}]}, project, section="Intro")])
    assert next(c for c in result.tracks[-1].clips if c.section_id == project.sections[0].id).notes[0].pitch == 69


def test_bounds_and_presets(project):
    for kind, params in [("notes", {"notes":[{"pitch":69,"start":31,"duration":2}]}), ("sound", {"preset":"drumkit"}), ("automation", {"parameter":"cutoff", "points":[[2,400], [1,9000]]})]:
        with pytest.raises(ValueError):
            apply_actions(project, [action(kind, params, project)])


def test_key_change_transposes_only_instruments(project):
    result = apply_actions(project, [Action(kind="project", params={"key":"B"})])
    assert result.tracks[0] == project.tracks[0]
    assert result.tracks[-1].clips[0].notes[0].pitch == project.tracks[-1].clips[0].notes[0].pitch + 2
    project.tracks[-1].locked = True
    with pytest.raises(ValueError, match="protected"):
        apply_actions(project, [Action(kind="project", params={"key":"B"})])


def test_cannot_remove_last_track(project):
    project.tracks = project.tracks[:1]
    with pytest.raises(ValueError, match="at least one"):
        apply_actions(project, [Action(kind="remove_track", track="drums")])


@pytest.mark.parametrize("role", ["drums", "bass", "chords", "lead"])
def test_variation_changes_the_music(project, role):
    from rdx.engine import generate_notes
    track = next(t for t in project.tracks if t.role == role)
    a = generate_notes(project, track, project.sections[2], variation=0)
    b = generate_notes(project, track, project.sections[2], variation=1)
    assert [n.model_dump(exclude={"id"}) for n in a] != [n.model_dump(exclude={"id"}) for n in b]


def test_unlock_and_edit_require_separate_decisions(project):
    project.tracks[0].locked = True
    with pytest.raises(ValueError, match="protected"):
        apply_actions(project, [Action(kind="protect",track="drums",params={"locked":False}),Action(kind="mix",track="drums",params={"delta_db":-2})])


def test_section_resize_trims_notes_and_interpolates_automation(project):
    project=apply_actions(project,[action("automation",{"parameter":"cutoff","points":[[0,400],[32,10000]]},project)])
    result=apply_actions(project,[action("arrange",{"operation":"update","bars":4},project)])
    assert result.sections[2].bars == 4
    assert result.tracks[-1].automation[0].points[-1] == (16,5200)


def test_pad_and_saw_presets_have_distinct_envelopes(project):
    saw=apply_actions(project,[action("sound",{"preset":"saw"},project)])
    pad=apply_actions(project,[action("sound",{"preset":"pad"},project)])
    assert pad.tracks[-1].sound.attack > saw.tracks[-1].sound.attack
    assert pad.tracks[-1].sound.release > saw.tracks[-1].sound.release


def test_active_training_adapter_cannot_be_overwritten(tmp_path, monkeypatch):
    from rdx import training
    monkeypatch.setattr(training,"ADAPTER",tmp_path)
    (tmp_path/"approved.json").write_text('{}')
    with pytest.raises(RuntimeError,match="protected"):
        training.main()
