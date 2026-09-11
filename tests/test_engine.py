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


# --- the contract, held against every action added since --------------------

EVERY_KIND = [
    Action(kind="sound", track="bass", params={"patch": "reese"}),
    Action(kind="kit_sound", track="drums", params={"machine": "808"}),
    Action(kind="sidechain", track="bass", params={"shape": "pump"}),
    Action(kind="phrase", track="lead", section="Main", params={"operation": "space"}),
    Action(kind="relate", track="bass", section="Main", params={"operation": "follow", "from_track": "chords"}),
    Action(kind="harmony", track="chords", section="Main", params={"progression": "trance"}),
    Action(kind="automation", track="lead", section="Main", params={"parameter": "drive", "points": [[0, 0], [8, 0.6]]}),
    Action(kind="arrange", section="Outro", params={"operation": "copy", "from_section": "Main"}),
    Action(kind="project", params={"scale": "dorian"}),
    Action(kind="move", params={"name": "pump"}),
    Action(kind="move", params={"name": "structure", "structure": "short"}),
    Action(kind="move", section="Main", params={"name": "stutter"}),
    Action(kind="move", section="Build", params={"name": "transition"}),
    Action(kind="move", section="Main", params={"name": "riser"}),
    Action(kind="move", section="Main", params={"name": "double_time"}),
    Action(kind="melody", track="lead", section="Main", params={"cell": "pluck", "shape": "wave", "form": "trance", "progression": "trance"}),
    # Naming neither a kit nor its layers decorates what is already playing,
    # which is a different path through the branch from generating a pattern.
    Action(kind="kit", track="drums", section="Main", params={"crash": True, "fill": True}),
    Action(kind="record", params={"genre": "trance"}),
]


@pytest.mark.parametrize("action", EVERY_KIND, ids=lambda a: f"{a.kind}:{a.params.get('name') or a.params.get('operation') or a.params.get('patch') or a.params.get('machine') or a.params.get('parameter') or a.params.get('progression') or a.params.get('scale') or ''}")
def test_no_action_mutates_the_project_it_was_given(action):
    project = starter_project()
    selection = {"track": next(t for t in project.tracks if t.role == "lead").id, "section": project.sections[2].id}
    before = project.model_dump_json()
    apply_actions(project, [action], selection)
    assert project.model_dump_json() == before, "apply_actions works on a copy or it is not undoable"


@pytest.mark.parametrize("action", EVERY_KIND, ids=lambda a: a.kind + (a.params.get("name") or ""))
def test_a_plan_that_fails_halfway_changes_nothing(action):
    """The second action is always impossible, so the first must be rolled back."""
    project = starter_project()
    selection = {"track": next(t for t in project.tracks if t.role == "lead").id, "section": project.sections[2].id}
    before = project.model_dump_json()
    with pytest.raises(ValueError):
        apply_actions(project, [action, Action(kind="character", track="Nonexistent", params={"character": "warm"})], selection)
    assert project.model_dump_json() == before


@pytest.mark.parametrize("action", EVERY_KIND, ids=lambda a: a.kind + (a.params.get("name") or ""))
def test_nothing_reaches_a_track_that_was_locked_when_the_edit_began(action):
    project = starter_project()
    selection = {"track": next(t for t in project.tracks if t.role == "lead").id, "section": project.sections[2].id}
    locked = apply_actions(project, [Action(kind="protect", track="all", params={"locked": True})], selection)
    frozen = {t.id: t.model_dump_json() for t in locked.tracks}
    try:
        after = apply_actions(locked, [action], selection)
    except ValueError:
        return  # refusing outright is the other correct answer
    for track in after.tracks:
        if track.id in frozen:
            assert track.model_dump_json() == frozen[track.id], f"{action.kind} touched a protected track"


@pytest.mark.parametrize("action", EVERY_KIND, ids=lambda a: a.kind + (a.params.get("name") or ""))
def test_every_result_is_a_project_that_can_be_stored_and_read_back(action):
    project = starter_project()
    selection = {"track": next(t for t in project.tracks if t.role == "lead").id, "section": project.sections[2].id}
    after = apply_actions(project, [action], selection)
    assert type(project).model_validate_json(after.model_dump_json()) == after


def test_long_chains_of_edits_never_produce_an_invalid_project():
    """Eight random edits, forty times over, from a fixed seed.

    Each action is tested on its own elsewhere. This is for what happens when
    they meet: a structure added after a section was shrunk, ducking on a track
    that was later duplicated, a mode change under a progression.
    """
    import random

    candidates = [
        ("sound", {"patch": "acid"}, "bass", None),
        ("kit_sound", {"machine": "909"}, "drums", None),
        ("sidechain", {"shape": "extreme"}, "bass", None),
        ("character", {"character": "wobbling", "intensity": 1.0}, "bass", None),
        ("phrase", {"operation": "fill", "amount": 1.0}, "lead", "Main"),
        ("relate", {"operation": "counter", "from_track": "drums"}, "lead", "Main"),
        ("harmony", {"progression": "andalusian", "colour": "ninth"}, "chords", "Main"),
        ("automation", {"parameter": "width", "points": [[0, 0], [8, 1]]}, "lead", "Main"),
        ("arrange", {"operation": "copy", "from_section": "Main"}, None, "Outro"),
        ("arrange", {"operation": "update", "bars": 2}, None, "Main"),
        ("project", {"scale": "phrygian"}, None, None),
        ("move", {"name": "buildup", "cut_bars": 1}, None, "Build"),
        ("move", {"name": "pump"}, None, None),
        ("move", {"name": "stutter", "beats": 2}, None, "Main"),
        ("move", {"name": "double_time"}, None, "Main"),
        ("move", {"name": "transition"}, None, "Build"),
        ("move", {"name": "layer", "track": "lead", "preset": "bell"}, None, None),
        ("duplicate_track", {}, "lead", None),
        ("transpose", {"semitones": -12}, "lead", "Main"),
        ("melody", {"cell": "roll", "shape": "hook", "form": "driving", "anchor": "chord", "progression": "epic"}, "lead", "Main"),
        ("melody", {"cell": "anthem", "shape": "ascent", "form": "answer", "progression": "trance"}, "lead", "Main"),
        ("kit", {"crash": True, "fill": True, "roll": True}, "drums", "Main"),
    ]
    for seed in range(40):
        rng = random.Random(seed)
        project = starter_project()
        selection = {"track": next(t for t in project.tracks if t.role == "lead").id, "section": project.sections[2].id}
        for _ in range(8):
            kind, params, track, section = rng.choice(candidates)
            try:
                project = apply_actions(project, [Action(kind=kind, track=track, section=section, params=dict(params))], selection)
            except ValueError:
                continue  # a refusal in plain language is a correct outcome
            type(project).model_validate(project.model_dump())


def test_a_project_saved_before_drum_voices_existed_gets_them_on_load():
    """Older files still have drums; they should still answer for their sound."""
    project = starter_project()
    raw = project.model_dump()
    for track in raw["tracks"]:
        track.pop("kit", None)
    loaded = type(project).model_validate(raw)
    drums = next(t for t in loaded.tracks if t.role == "drums")
    assert drums.kit is not None and drums.kit.kick_decay > 0
    assert all(t.kit is None for t in loaded.tracks if t.role != "drums")
