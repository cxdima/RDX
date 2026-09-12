"""Tests for whole records, asserting the things that make a genre that genre.

These are the most arguable claims in the project. If the psytrance bass should
be sixteenths rather than three-after-the-kick, this is the file that says what
RDX currently believes, and changing the belief means changing a test that
spells out the musical consequence.
"""
from __future__ import annotations

import pytest

from rdx.domain import Action, Automation, Clip, PITCH_CLASSES, Section, SCALE_STEPS, new_track
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
    root = PITCH_CLASSES.index(record.key)  # the record's own tonic, not a fixed A
    allowed = {(root + step) % 12 for step in steps}
    borrowed = {(root + steps[4] + 4) % 12}  # the major third of the fifth degree
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


def test_a_record_lays_out_its_own_arrangement(selection):
    """Asking for a record means a record.

    Appending instead produced a trance record bolted onto the end of the
    starter demo: 116 bars, four dead sections in front of it and a section
    called "Build 2 2". This is destructive and allowed to be, because the whole
    record is one atomic edit the user previews before accepting."""
    project = starter_project()
    record = apply_actions(project, [Action(kind="record", params={"genre": "trance"})], {"track": project.tracks[0].id, "section": project.sections[0].id})
    names = [s.name for s in record.sections]
    assert names == ["Intro", "Build", "Drop", "Breakdown", "Build 2", "Drop 2", "Outro"]
    assert not any(name.endswith(" 2 2") for name in names)
    assert [s.name for s in project.sections] == ["Intro", "Build", "Main", "Outro"], "and the original is untouched"


def test_a_record_can_be_appended_to_one_that_is_already_there(selection):
    """For putting a second record in the same project, which is the reason the
    replacing version needs a way to be switched off."""
    project = starter_project()
    before = {s.name: sum(len(c.notes) for t in project.tracks for c in t.clips if c.section_id == s.id) for s in project.sections}
    record = apply_actions(project, [Action(kind="record", params={"genre": "trance", "replace": False})], {"track": project.tracks[0].id, "section": project.sections[0].id})
    after = {s.name: sum(len(c.notes) for t in record.tracks for c in t.clips if c.section_id == s.id) for s in record.sections}
    for name, count in before.items():
        assert after.get(name) == count, f"{name} was disturbed"
    assert len(record.sections) > len(project.sections)


def test_appending_preserves_recordings_automation_and_intentional_silence():
    project = starter_project()
    recording, silence = Section(name="Recording", bars=2), Section(name="Pause", bars=1)
    project.sections.extend([recording, silence])
    audio = new_track("audio")
    audio.clips = [Clip(section_id=recording.id, audio_id="123456789abc")]
    audio.automation = [Automation(section_id=silence.id, parameter="volume_db", points=[(0, -6), (4, -60)])]
    project.tracks.append(audio)
    before = project.model_dump()
    result = apply_actions(project, [Action(kind="record", params={"genre": "trance", "replace": False})])
    assert result.sections[:len(project.sections)] == project.sections
    after = next(t for t in result.tracks if t.id == audio.id)
    assert after.clips == audio.clips
    assert [a for a in after.automation if a.section_id in {recording.id, silence.id}] == audio.automation
    assert project.model_dump() == before


def test_a_genre_rdx_does_not_know_is_refused_by_name(blank, selection):
    with pytest.raises(Unsupported, match="trance"):
        apply_actions(blank, [Action(kind="record", params={"genre": "dubstep"})], selection)


def test_a_record_cannot_be_nested_inside_another_edit(blank, selection):
    with pytest.raises(EditError, match="whole arrangement"):
        apply_actions(blank, [Action(kind="record", params={"genre": "trance"})], selection, None, None, 1)


def a_trance_record():
    return apply_actions(starter_project(), [Action(kind="record", params={"genre": "trance"})])


def drum_notes(project, section_name):
    drums = next(t for t in project.tracks if t.role == "drums")
    section = next(s for s in project.sections if s.name == section_name)
    return next(c for c in drums.clips if c.section_id == section.id).notes


def test_a_transition_does_not_cost_the_next_section_its_drums():
    """The bug this exists to prevent.

    A transition puts a crash on the section it leads into. RDX answered that by
    generating a fresh kit, which replaced a mainstage drop — double claps,
    sixteenth hats, offbeat opens — with a default four-to-the-floor pattern,
    and reported success. 450 notes became 289. An edit that looks like it
    worked and quietly did something else is the worst outcome in the project.
    """
    record = a_trance_record()
    before = drum_notes(record, "Drop")
    build = next(s for s in record.sections if s.name == "Build")
    after = drum_notes(apply_actions(record, [Action(kind="move", section=build.id, params={"name": "transition"})]), "Drop")
    assert len(after) >= len(before), f"the drop lost {len(before) - len(after)} notes"
    assert {n.pitch for n in before} <= {n.pitch for n in after}, "and it kept every voice it was playing"


def test_a_crash_is_added_to_the_pattern_rather_than_replacing_it():
    from rdx.musical.drums import CRASH
    record = a_trance_record()
    breakdown = next(s for s in record.sections if s.name == "Breakdown")
    before = drum_notes(record, "Breakdown")
    assert not any(n.pitch == CRASH for n in before), "nothing to start with"
    after = drum_notes(apply_actions(record, [Action(kind="kit", track="drums", section=breakdown.id, params={"crash": True})]), "Breakdown")
    assert len(after) == len(before) + 1
    assert sum(1 for n in after if n.pitch == CRASH) == 1


def test_a_second_crash_does_not_stack_on_the_first():
    from rdx.musical.drums import CRASH
    record = a_trance_record()
    drop = next(s for s in record.sections if s.name == "Drop")
    twice = apply_actions(record, [Action(kind="kit", track="drums", section=drop.id, params={"crash": True})] * 2)
    assert sum(1 for n in drum_notes(twice, "Drop") if n.pitch == CRASH) == 1


def test_changing_density_without_naming_a_pattern_is_refused_rather_than_guessed():
    """RDX cannot thin a pattern it cannot see the make-up of, and inventing a
    default one to thin is how the drop got replaced in the first place."""
    record = a_trance_record()
    drop = next(s for s in record.sections if s.name == "Drop")
    with pytest.raises(EditError, match="density"):
        apply_actions(record, [Action(kind="kit", track="drums", section=drop.id, params={"density": 0.4})])


def test_a_bare_kit_on_an_empty_section_still_writes_drums(blank, selection):
    """Decorating nothing has to fall back to making something."""
    section = blank.sections[0].id
    written = apply_actions(blank, [Action(kind="kit", track="drums", section=section, params={"crash": True})])
    drums = next(t for t in written.tracks if t.role == "drums")
    assert any(c.section_id == section and c.notes for c in drums.clips)


def test_a_fill_announces_every_section_that_leads_somewhere_bigger():
    """The clearest signal in dance music that something is about to change.
    Without it an arrangement reads as a loop that changes length rather than a
    record that goes somewhere."""
    from rdx.musical.drums import HIGH_TOM, LOW_TOM, MID_TOM
    record = a_trance_record()
    toms = {HIGH_TOM, MID_TOM, LOW_TOM}
    filled = set()
    for section in record.sections:
        notes = drum_notes(record, section.name)
        hits = [n for n in notes if n.pitch in toms]
        if hits:
            filled.add(section.name)
            assert all(n.start >= (section.bars - 1) * 4 for n in hits), "a fill belongs in the last bar"
    rising = {a.name for a, b in zip(record.sections, record.sections[1:]) if b.energy > a.energy + 0.1}
    assert filled, "something should fill"
    assert filled <= rising, f"{filled - rising} filled without leading anywhere bigger"
    assert not any(name.split()[0].lower() == "build" for name in filled), "builds end on a roll instead"


def test_a_breakdown_keeps_the_melody_and_the_pulse_but_loses_the_weight():
    """Two rules meet here.

    The melody stays, because a trance breakdown is where the tune you remember
    lives. And the beat stays, because — a producer's rule for arranging —
    a crowd cannot dance unless it knows where the beat is, so something
    rhythmic keeps running whenever the kick drops out. What goes is the weight:
    the kick, the clap and the bass.
    """
    from rdx.musical.drums import CLAP, HAT, KICK

    record = a_trance_record()
    breakdown = next(s for s in record.sections if s.name == "Breakdown")
    quiet = {}
    for track in record.tracks:
        lane = next((a for a in track.automation if a.section_id == breakdown.id and a.parameter == "volume_db"), None)
        quiet[track.role] = bool(lane) and max(value for _, value in lane.points) <= -40

    assert quiet.get("bass"), "the bass goes"
    assert not quiet.get("lead"), "the melody stays"
    assert not quiet.get("drums"), "and the kit is not silenced outright"

    playing = {n.pitch for n in drum_notes(record, "Breakdown")}
    assert HAT in playing, "something keeps the time"
    assert KICK not in playing and CLAP not in playing, "but the weight is gone"

    lead = next(t for t in record.tracks if t.role == "lead")
    assert any(c.section_id == breakdown.id and c.notes for c in lead.clips), "and the tune has something to play"


def test_a_breakdown_does_not_change_how_the_drops_sound():
    """A sound belongs to the track, not to the section, so a breakdown that
    reaches for a character change reaches for all of it.

    Making the pads dreamy in the breakdown left the lead carrying both drops
    with a 0.2 second attack, which is the opposite of what a trance pluck is
    for. Reverb and cutoff say the same thing and stop at the section line.
    """
    from rdx.musical import moves

    record = a_trance_record()
    breakdown = next(s for s in record.sections if s.name == "Breakdown")
    before = {t.id: t.sound.model_dump() for t in record.tracks}
    after = apply_actions(record, [Action(kind="move", section=breakdown.id, params={"name": "breakdown"})])
    for track in after.tracks:
        assert track.sound.model_dump() == before[track.id], f"{track.name}'s sound was changed for the whole record"
    lanes = [a for t in after.tracks for a in t.automation if a.section_id == breakdown.id]
    assert any(a.parameter == "reverb" for a in lanes), "the space is still there"
    assert any(a.parameter == "cutoff" for a in lanes), "and so is the softening"


@pytest.mark.parametrize("genre", sorted(genres.GENRES))
def test_the_hook_is_held_back_from_the_intro(genre):
    """A melody playing from bar one is a melody nobody gets to wait for.

    The intro sets the record up and the outro winds it down; the tune belongs
    to everything between them, and a breakdown exists precisely so it can
    arrive somewhere.
    """
    record = apply_actions(starter_project(), [Action(kind="record", params={"genre": genre})])
    lead = next((t for t in record.tracks if t.role == "lead"), None)
    if lead is None:
        pytest.skip(f"{genre} has no lead")
    played = {
        s.name.split()[0].lower()
        for s in record.sections
        if any(c.section_id == s.id and c.notes for c in lead.clips)
    }
    assert "intro" not in played and "outro" not in played
    assert played, f"{genre}: the lead never plays at all"
    assert "drop" in played or "main" in played, "and it plays where the record is loudest"


@pytest.mark.parametrize("genre", sorted(genres.GENRES))
def test_every_genre_makes_a_record_rather_than_a_sketch(genre):
    """`record` is called record. Techno and hardstyle were both handed the
    "short" structure — 40 bars, described in moves.py as "for working an idea
    out before committing" — and rendered as 67 and 76 second sketches. The
    short shape is still there to ask for; it is not what a record means."""
    from rdx.musical.moves import STRUCTURES

    made = apply_actions(starter_project(), [Action(kind="record", params={"genre": genre})])
    bars = sum(s.bars for s in made.sections)
    minutes = bars * 4 / genres.GENRES[genre].tempo
    assert bars >= 64, f"{genre} lays out {bars} bars"
    assert minutes >= 2.0, f"{genre} runs {minutes:.1f} minutes"
    assert genres.GENRES[genre].structure in STRUCTURES
    # Two moments of full energy, or one with a long breakdown leading to it.
    drops = [s for s in made.sections if s.name.split()[0].lower() in genres.ENERGETIC]
    quiet = [s for s in made.sections if s.name.split()[0].lower() in genres.QUIET]
    assert drops and quiet, f"{genre}: {[s.name for s in made.sections]}"


def test_a_transition_into_a_drop_and_into_a_breakdown_are_not_the_same_thing():
    """The last open item in the handoff: a join that knows what it joins to.

    A crash on the first bar of a breakdown is a door slamming in a quiet room,
    and a half-beat of silence before something already quiet is just a hole.
    """
    from rdx.musical import moves

    record = a_trance_record()
    into_drop = next(s for s in record.sections if s.name == "Build")
    into_breakdown = next(s for s in record.sections if s.name == "Drop")

    def gestures(section):
        actions = moves.transition(record, section.id)
        return {
            "crash": any(a.kind == "kit" and a.params.get("crash") for a in actions),
            "gap": any(a.kind == "automation" and a.params.get("parameter") == "volume_db" for a in actions),
            "sweep": any(a.kind == "automation" and a.params.get("parameter") == "cutoff" for a in actions),
        }

    up, down = gestures(into_drop), gestures(into_breakdown)
    assert up["crash"] and up["gap"], "into a drop: the crash and the gap that make it land"
    assert not down["crash"] and not down["gap"], "into a breakdown: neither"
    assert up["sweep"] and down["sweep"], "the filter opens up either way"

    # Asking for one explicitly still gets it, wherever it leads.
    forced = moves.transition(record, into_breakdown.id, crash=True)
    assert any(a.kind == "kit" and a.params.get("crash") for a in forced)


def test_the_second_drop_is_the_same_tune_an_octave_higher():
    """A record that plays its second drop note-for-note stops going anywhere
    halfway through. One that plays a different tune throws away the hook you
    have been waiting twelve bars for. Trance has done the same thing with a
    final drop for thirty years: the same melody, an octave up."""
    record = a_trance_record()
    lead = next(t for t in record.tracks if t.role == "lead")

    def line(name):
        section = next(s for s in record.sections if s.name == name)
        clip = next(c for c in lead.clips if c.section_id == section.id)
        return sorted(clip.notes, key=lambda n: (n.start, n.pitch))

    first, again = line("Drop"), line("Drop 2")
    assert len(first) == len(again), "the same phrase"
    assert [n.start for n in first] == [n.start for n in again], "in the same rhythm"
    assert {b.pitch - a.pitch for a, b in zip(first, again)} == {12}, "exactly an octave up"


@pytest.mark.parametrize("genre", sorted(genres.GENRES))
def test_no_section_of_any_record_is_silent(genre):
    """A record has to make a sound all the way through.

    This exists because of a bug nothing else could see: automation was held
    past the section it was drawn in, so a buildup's cut to -60 dB before the
    drop silenced every section after it. Every Python test passed — the notes
    were all there and the automation was correct — and a rendered record
    measured -75 dBFS through its own drop.

    So a section counts as alive only if some track has notes in it *and* is not
    automated into silence there.
    """
    record = apply_actions(starter_project(), [Action(kind="record", params={"genre": genre})])
    for section in record.sections:
        alive = []
        for track in record.tracks:
            notes = sum(len(c.notes) for c in track.clips if c.section_id == section.id)
            lane = next((a for a in track.automation if a.section_id == section.id and a.parameter == "volume_db"), None)
            if notes and not (lane and max(value for _, value in lane.points) <= -40):
                alive.append(track.name)
        assert alive, f"{genre}: {section.name} plays nothing"


@pytest.mark.parametrize("genre", sorted(genres.GENRES))
def test_no_drop_is_quieter_than_the_build_that_leads_into_it(genre):
    """a professional producer calls this a big problem in dance music: they listened
    back and found the lead-up to the drop was louder than the drop.

    It is also the exact shape of the automation bug that made this project's
    records silent — a buildup's cut to -60 dB before the drop stayed in force
    through the drop itself. So the drop must have at least as many parts
    playing as the build, and none of them turned down.
    """
    record = apply_actions(starter_project(), [Action(kind="record", params={"genre": genre})])
    sections = record.sections

    def playing(section):
        alive = 0
        for track in record.tracks:
            notes = sum(len(c.notes) for c in track.clips if c.section_id == section.id)
            lane = next((a for a in track.automation if a.section_id == section.id and a.parameter == "volume_db"), None)
            floor = min((value for _, value in lane.points), default=0.0) if lane else 0.0
            if notes and floor > -40:
                alive += 1
        return alive

    for build, drop in zip(sections, sections[1:]):
        if build.name.split()[0].lower() != "build" or drop.name.split()[0].lower() not in genres.ENERGETIC:
            continue
        assert playing(drop) >= playing(build), f"{genre}: {drop.name} has fewer parts than {build.name}"
        for track in record.tracks:
            lane = next((a for a in track.automation if a.section_id == drop.id and a.parameter == "volume_db"), None)
            if lane:
                assert min(value for _, value in lane.points) > -40, f"{genre}: {track.name} is turned down in {drop.name}"


def test_the_melody_is_teased_before_it_is_stated():
    """"Find ways to tease your main melody" — a professional producer on arranging.

    The hook is kept out of the intro entirely, arrives in the build under a
    filter that opens from 500 Hz, and only lands in full at the drop. So its
    first appearance is both sparser per bar and darker than its last.
    """
    record = a_trance_record()
    lead = next(t for t in record.tracks if t.role == "lead")
    build = next(s for s in record.sections if s.name == "Build")
    drop = next(s for s in record.sections if s.name == "Drop")

    def per_bar(section):
        clip = next((c for c in lead.clips if c.section_id == section.id), None)
        return len(clip.notes) / section.bars if clip else 0

    assert per_bar(build) < per_bar(drop), "the tease is sparser than the statement"

    sweep = next((a for a in lead.automation if a.section_id == build.id and a.parameter == "cutoff"), None)
    assert sweep, "and it arrives under a filter"
    opens_from = sweep.points[0][1]
    assert opens_from < 1000, f"a tease starts dark, not at {opens_from} Hz"
    assert sweep.points[-1][1] > opens_from * 4, "and opens up into the drop"

    intro = next(s for s in record.sections if s.name == "Intro")
    assert not any(c.section_id == intro.id and c.notes for c in lead.clips), "nothing is given away in the intro"
