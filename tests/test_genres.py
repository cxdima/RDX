"""Tests for whole records, asserting the things that make a genre that genre.

These are the most arguable claims in the project. If the psytrance bass should
be sixteenths rather than three-after-the-kick, this is the file that says what
RDX currently believes, and changing the belief means changing a test that
spells out the musical consequence.
"""
from __future__ import annotations

import pytest

from rdx.domain import Action, SCALE_STEPS
from rdx.engine import EditError, Unsupported, apply_actions, starter_project
from rdx.musical import bass, genres
from rdx.musical.drums import KICK


@pytest.fixture
def blank():
    """Tracks but nothing written — what a new project gives you."""
    project = starter_project()
    for track in project.tracks:
        track.clips = []
    return type(project).model_validate(project.model_dump())


@pytest.fixture
def selection(blank):
    return {"track": blank.tracks[0].id, "section": blank.sections[0].id}


def made(blank, selection, genre: str):
    return apply_actions(blank, [Action(kind="record", params={"genre": genre})], selection)


def notes_in(project, role: str, section_name: str) -> list:
    section = next(s for s in project.sections if s.name == section_name)
    track = next((t for t in project.tracks if t.role == role), None)
    if track is None:
        return []
    clip = next((c for c in track.clips if c.section_id == section.id), None)
    return clip.notes if clip else []


# --- the bassline, which is where a genre lives ----------------------------


def test_a_trance_bass_never_lands_on_a_kick(blank, selection):
    """Offbeat bass against a four-floor kick is the whole feel."""
    record = made(blank, selection, "trance")
    kicks = {round(n.start, 4) for n in notes_in(record, "drums", "Drop") if n.pitch == KICK}
    bass_hits = {round(n.start, 4) for n in notes_in(record, "bass", "Drop")}
    assert bass_hits and kicks
    assert not (bass_hits & kicks), "a trance bass plays between the kicks, not on them"
    assert all(abs(hit % 1 - 0.5) < 1e-6 for hit in bass_hits), "and it plays on the offbeats"


def test_a_psytrance_bass_plays_three_sixteenths_after_every_kick(blank, selection):
    record = made(blank, selection, "psytrance")
    kicks = {round(n.start, 4) for n in notes_in(record, "drums", "Drop") if n.pitch == KICK}
    bass_hits = sorted({round(n.start, 4) for n in notes_in(record, "bass", "Drop")})
    assert not (set(bass_hits) & kicks), "the defining rule: never on the kick"
    first_beat = [hit for hit in bass_hits if hit < 1]
    assert first_beat == [0.25, 0.5, 0.75], "three sixteenths, filling the gap"


def test_every_bass_pattern_follows_the_chord_progression(blank, selection):
    """The bass takes its pitches from the harmony, not from the key alone."""
    from rdx.musical import harmony

    entries = harmony.named("trance", 4, "A", "minor")
    for pattern in bass.PATTERNS:
        line = bass.line(pattern, entries, 4)
        assert line, pattern
        for note in line:
            sounding = next(c for start, length, c in entries if start <= note.start < start + length)
            assert note.pitch % 12 == sounding.root_pc, f"{pattern} strayed off the chord root"


def test_a_bassline_stays_inside_its_section():
    from rdx.musical import harmony

    entries = harmony.named("trance", 2, "A", "minor")
    for pattern in bass.PATTERNS:
        for note in bass.line(pattern, entries, 2):
            assert note.start + note.duration <= 8 + 1e-9, pattern


# --- the record as a whole --------------------------------------------------


@pytest.mark.parametrize("name", list(genres.GENRES))
def test_every_genre_makes_a_playable_record(blank, selection, name):
    record = made(blank, selection, name)
    genre = genres.GENRES[name]
    assert record.tempo == genre.tempo and record.scale == genre.scale
    assert sum(s.bars for s in record.sections) >= 40, "a record is not four bars"
    written = sum(len(c.notes) for t in record.tracks for c in t.clips)
    assert written > 200, f"{name} produced almost nothing"


@pytest.mark.parametrize("name", list(genres.GENRES))
def test_every_record_stays_in_its_key(blank, selection, name):
    """With one deliberate exception: the borrowed major V.

    A minor key leans on a raised seventh going into the tonic, and
    harmony.diatonic offers that chord on purpose. It is the only note in a
    record that comes from outside the scale, and this pins it to that.
    """
    record = made(blank, selection, name)
    steps = SCALE_STEPS[record.scale]
    allowed = {(9 + step) % 12 for step in steps}
    borrowed = {(9 + steps[4] + 4) % 12}  # the major third of the fifth degree
    for track in record.tracks:
        if track.role in {"drums", "audio"} or track.name == "Riser":
            continue
        for clip in track.clips:
            for note in clip.notes:
                assert note.pitch % 12 in allowed | borrowed, f"{name}: {track.name} left {record.key} {record.scale}"


def test_psytrance_has_no_pad_chords_under_it(blank, selection):
    """A psytrance record with big chords under it is not a psytrance record."""
    record = made(blank, selection, "psytrance")
    assert sum(len(c.notes) for t in record.tracks if t.role == "chords" for c in t.clips) == 0
    assert sum(len(c.notes) for t in record.tracks if t.role == "bass" for c in t.clips) > 0


def test_a_drop_is_busier_than_the_breakdown_before_it(blank, selection):
    record = made(blank, selection, "trance")
    drop = sum(len(notes_in(record, role, "Drop")) for role in ("drums", "bass", "chords", "lead"))
    breakdown = sum(len(notes_in(record, role, "Breakdown")) for role in ("drums", "bass", "chords", "lead"))
    assert drop > breakdown * 1.5, "the drop should arrive as a release"


def test_everything_melodic_ducks_under_the_kick(blank, selection):
    record = made(blank, selection, "trance")
    ducked = {t.name for t in record.tracks if t.sidechain}
    assert {"Bass", "Chords", "Lead"} <= ducked
    assert not any(t.sidechain for t in record.tracks if t.role == "drums")


def test_a_record_leaves_existing_music_alone(selection):
    """Sections with something in them are kept; the record lands after them."""
    project = starter_project()
    before = {s.name: sum(len(c.notes) for t in project.tracks for c in t.clips if c.section_id == s.id) for s in project.sections}
    record = apply_actions(project, [Action(kind="record", params={"genre": "trance"})], {"track": project.tracks[0].id, "section": project.sections[0].id})
    after = {s.name: sum(len(c.notes) for t in record.tracks for c in t.clips if c.section_id == s.id) for s in record.sections}
    for name, count in before.items():
        assert after.get(name) == count, f"{name} was disturbed"


def test_a_genre_rdx_does_not_know_is_refused_by_name(blank, selection):
    with pytest.raises(Unsupported, match="trance"):
        apply_actions(blank, [Action(kind="record", params={"genre": "dubstep"})], selection)


def test_a_record_cannot_be_nested_inside_another_edit(blank, selection):
    with pytest.raises(EditError, match="whole arrangement"):
        apply_actions(blank, [Action(kind="record", params={"genre": "trance"})], selection, None, None, 1)
