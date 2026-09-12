"""What makes a melody a melody rather than a stream of notes.

Every test here is a claim about music that a producer can argue with. The one
that matters most is the last: the shape RDX writes must measurably differ from
the shape it replaced, which was eight random scale degrees replayed every bar.
"""
from __future__ import annotations

import pytest

from rdx.domain import SCALE_STEPS, PITCH_CLASSES
from rdx.musical import harmony, motif

PROGRESSION = harmony.named("trance", 8, "A", "minor")


def phrase(**kwargs):
    settings = {"cell": "pluck", "shape": "wave", "form": "trance", "entries": PROGRESSION, "bars": 8, "key": "A", "scale": "minor"}
    settings.update(kwargs)
    return motif.line(settings.pop("cell"), settings.pop("shape"), settings.pop("form"), settings.pop("entries"), settings.pop("bars"), **settings)


def bar(notes, index):
    return [n for n in notes if index * 4 <= n.start < index * 4 + 4]


def test_a_repeated_bar_is_actually_the_same_bar():
    """The whole reason a melody is memorable. A generator that varies every
    bar gives the ear nothing to hold, which is what 'it sounds simple' meant."""
    notes = phrase()
    stated, repeated = bar(notes, 0), bar(notes, 1)
    assert [n.pitch for n in stated] == [n.pitch for n in repeated]
    assert [n.start % 4 for n in stated] == [n.start % 4 for n in repeated]


def test_a_sequence_climbs_above_the_bar_it_answers():
    notes = phrase()
    assert motif.FORMS["trance"][4] == "sequence"
    assert max(n.pitch for n in bar(notes, 4)) > max(n.pitch for n in bar(notes, 2))


def test_the_peak_bar_really_is_the_highest_point_of_the_phrase():
    """A climax that is merely near the top is not a climax."""
    notes = phrase()
    peak = motif.FORMS["trance"].index("peak")
    elsewhere = max(n.pitch for i in range(8) if i != peak for n in bar(notes, i))
    assert max(n.pitch for n in bar(notes, peak)) > elsewhere


def test_the_phrase_ends_at_home_and_holds():
    notes = phrase()
    last = max(notes, key=lambda n: n.start)
    assert last.pitch % 12 == PITCH_CLASSES.index("A"), "a melody that never lands is a question"
    assert last.duration > 0.5, "and the note it lands on is held"


def test_an_open_bar_leaves_the_question_hanging_on_the_fifth():
    notes = phrase()
    opened = motif.FORMS["trance"].index("open")
    last = max(bar(notes, opened), key=lambda n: n.start)
    assert (last.pitch - PITCH_CLASSES.index("A")) % 12 == SCALE_STEPS["minor"][4]


def test_every_note_on_beat_one_or_three_belongs_to_the_chord_underneath():
    """The single constraint that separates a line sitting inside the harmony
    from one arguing with it.

    Only the strongest beats. Pulling every whole beat onto a chord tone leaves
    no room for the passing notes a melody is mostly made of, and moves the same
    degree far enough between two bars that the ear stops hearing one idea."""
    notes = phrase()
    for note in notes:
        if motif.weight(note.start % 4) != 3:
            continue
        chord = motif.chord_at(PROGRESSION, note.start)
        assert note.pitch % 12 in chord.pitch_classes, f"{note.pitch} at beat {note.start} is outside {chord.symbol}"


@pytest.mark.parametrize("scale", sorted(SCALE_STEPS))
@pytest.mark.parametrize("shape", sorted(motif.SHAPES))
def test_a_melody_never_leaves_the_key(scale, shape):
    entries = harmony.named("trance", 8, "D", scale)
    allowed = {(PITCH_CLASSES.index("D") + step) % 12 for step in SCALE_STEPS[scale]}
    for note in phrase(shape=shape, entries=entries, key="D", scale=scale):
        assert note.pitch % 12 in allowed


@pytest.mark.parametrize("cell", sorted(motif.CELLS))
@pytest.mark.parametrize("form", sorted(motif.FORMS))
def test_a_melody_never_leaves_its_section(cell, form):
    for note in phrase(cell=cell, form=form, bars=4, entries=harmony.named("trance", 4, "A", "minor")):
        assert note.start + note.duration <= 16 + 1e-6


def test_thinning_keeps_the_strong_beats_and_drops_the_rest():
    full, thin = phrase(density=1.0), phrase(density=0.5)
    assert len(thin) < len(full)
    kept = {round(n.start % 4, 4) for n in thin}
    assert 0.0 in kept, "the downbeat survives any thinning"
    assert all(motif.weight(p) >= 1 for p in kept), "and what survives is the skeleton"


def test_a_rest_is_silence_rather_than_quiet_notes():
    notes = phrase(form="answer")
    assert motif.FORMS["answer"][1] == "rest"
    assert bar(notes, 1) == []


def test_the_composed_phrase_is_measurably_more_than_a_looped_one():
    """The claim this module exists to make. `loop` is what the old generator
    did — one bar, eight times — and is kept so the difference is a number
    rather than an opinion."""
    composed, looped = phrase(form="trance"), phrase(form="loop")
    span = lambda ns: max(n.pitch for n in ns) - min(n.pitch for n in ns)
    shapes = lambda ns: {tuple(n.pitch for n in bar(ns, i)) for i in range(8)}
    assert span(composed) > span(looped), "it goes somewhere"
    assert len(shapes(composed)) > len(shapes(looped)), "and it develops on the way"


def test_anchoring_to_the_chord_transposes_the_idea_with_the_harmony():
    fixed, moving = phrase(anchor="key"), phrase(anchor="chord")
    assert [n.pitch for n in bar(fixed, 0)] == [n.pitch for n in bar(fixed, 1)]
    assert [n.pitch for n in bar(moving, 0)] != [n.pitch for n in bar(moving, 1)]


@pytest.mark.parametrize("bad", [{"cell": "nope"}, {"shape": "nope"}, {"form": "nope"}])
def test_the_generator_refuses_an_unknown_cell_shape_or_form(bad):
    """Straight at `line`. The engine turns this into an `Unsupported` the user
    reads — see the test at the bottom of this file."""
    with pytest.raises(KeyError):
        phrase(**bad)


def test_a_melody_without_chords_is_refused():
    with pytest.raises(ValueError):
        phrase(entries=[])


@pytest.mark.parametrize("shape", sorted(motif.SHAPES))
def test_the_idea_never_leaps_an_octave_between_bars(shape):
    """Moving the idea onto the next chord means moving it to the nearest place
    that chord sits. Counting up from the tonic instead puts a chord on the
    seventh degree a tenth above the bar before it, and a line that jumps like
    that every other bar stops being one line."""
    notes = phrase(shape=shape, anchor="chord")
    centres = [sum(n.pitch for n in bar(notes, i)) / len(bar(notes, i)) for i in range(8) if bar(notes, i)]
    assert max(abs(b - a) for a, b in zip(centres, centres[1:])) < 12


@pytest.mark.parametrize("form", sorted(motif.FORMS))
@pytest.mark.parametrize("cell", sorted(motif.CELLS))
def test_every_melody_can_be_described(cell, form):
    """The description is the only account of the edit the user gets, and it is
    generated on the engine's findings path — so a melody RDX can write and
    cannot describe crashes the request instead of answering it."""
    told = motif.describe(cell, "wave", form)
    assert motif.CELLS[cell].meaning in told
    assert "wave" in told and told.strip() == told


def test_every_form_is_built_from_developments_that_exist():
    """A form naming a development nobody wrote raises at generation time, and
    one missing from the description table crashes the sentence the user reads.
    Both are only reachable through a form, so the forms are checked instead."""
    for name, plan in motif.FORMS.items():
        unknown = set(plan) - set(motif.DEVELOPMENTS)
        assert not unknown, f"{name} uses {unknown}"
        assert not set(plan) - set(motif.TOLD), f"{name} has a development with no wording"
    assert set(motif.TOLD) == set(motif.DEVELOPMENTS), "every development is described"


def test_every_form_states_an_idea_before_developing_it():
    """A phrase that opens on its own peak, or on a rest, has nothing to
    develop. Whatever else a form does, it has to begin by saying the thing."""
    for name, plan in motif.FORMS.items():
        assert plan[0] == "state", f"{name} opens on {plan[0]!r}"


@pytest.mark.parametrize("setting", ["cell", "shape", "form", "anchor"])
def test_a_melody_setting_rdx_does_not_know_is_refused_by_name(setting):
    """`Unsupported`, not a validation failure. The server sends these straight
    to the user rather than asking the model to try again, because rephrasing
    cannot conjure a shape nobody wrote."""
    from rdx.domain import Action
    from rdx.engine import Unsupported, apply_actions, starter_project

    project = starter_project()
    section = next(s for s in project.sections if s.name == "Main")
    with pytest.raises(Unsupported, match="RDX knows"):
        apply_actions(project, [Action(kind="melody", track="lead", section=section.id, params={setting: "banana", "progression": "trance"})])


@pytest.mark.parametrize("bars", [1, 2, 3, 5, 8, 13, 16, 32, 64])
def test_every_cell_and_form_works_at_every_section_length(bars):
    """A form is eight bars of plan, and a section is anything from one bar to
    sixty-four. The plan cycles, which means a two-bar section only ever hears
    the opening of an idea and a sixteen-bar one hears it twice — both fine, and
    neither allowed to write a note past the section or outside MIDI."""
    entries = harmony.named("trance", bars, "A", "minor")
    for cell in motif.CELLS:
        for form in motif.FORMS:
            written = motif.line(cell, "wave", form, entries, bars, key="A", scale="minor")
            for note in written:
                assert note.start + note.duration <= bars * 4 + 1e-6, f"{cell}/{form} overruns"
                assert 0 <= note.pitch <= 127
                assert note.duration > 0


@pytest.mark.parametrize("low,high", [(60, 65), (120, 127), (0, 8), (90, 60), (-1, 88), (60, 128)])
def test_an_impossible_register_is_refused_without_clipping_the_melody(low, high):
    # Clamping to MIDI 127 turned high C# major phrases into G naturals.
    # Refusal preserves the idea instead of silently breaking its key or shape.
    from rdx.domain import Action
    from rdx.engine import EditError, apply_actions, starter_project

    project = starter_project()
    project.key, project.scale = "C#", "major"
    before = project.model_dump()
    with pytest.raises(EditError, match="register"):
        apply_actions(project, [Action(kind="melody", track="lead", section="Main", params={
            "shape": "climb", "progression": "trance", "low": low, "high": high,
        })])
    assert project.model_dump() == before


@pytest.mark.parametrize("key", PITCH_CLASSES)
@pytest.mark.parametrize("low,high", [(0, 36), (48, 84), (91, 127)])
def test_register_placement_keeps_every_pitch_in_range_and_in_key(key, low, high):
    notes = phrase(key=key, scale="major", entries=harmony.named("trance", 8, key, "major"), low=low, high=high)
    allowed = {(PITCH_CLASSES.index(key) + step) % 12 for step in SCALE_STEPS["major"]}
    assert all(low <= n.pitch <= high and n.pitch % 12 in allowed for n in notes)


def test_chord_snapping_follows_a_change_inside_the_bar():
    entries = harmony.from_degrees(harmony.parse_progression("i-VII"), 1, "D", "minor", span=2)
    notes = phrase(cell="stab", shape="hover", form="loop", entries=entries, bars=1, key="D", scale="minor")
    assert [n.start for n in notes] == [0, 2]
    assert all(n.pitch % 12 in motif.chord_at(entries, n.start).pitch_classes for n in notes)


def test_borrowed_harmony_cannot_snap_a_melody_out_of_its_key():
    # E major is a real borrowed dominant in A minor. Its G# must not silently
    # replace the melody's A when this generator promises the project scale.
    entries = [(0, 4, harmony.Chord(4, 4, "major"))]
    notes = phrase(cell="stab", shape="hover", form="loop", entries=entries, bars=1)
    assert all(n.pitch % 12 in {9, 11, 0, 2, 4, 5, 7} for n in notes)
