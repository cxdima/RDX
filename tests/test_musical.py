"""Tests for the musical knowledge RDX owns in code.

These assert musical results, not that a function returned. If a producer
disagrees with what "warm" or "buildup" means, the argument happens here.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from rdx.domain import Action, Clip, DRUM_MAP, Note, Sound
from rdx.engine import EditError, Unsupported, apply_actions, starter_project
from rdx.musical import drums, harmony, moves
from rdx.musical.character import CHARACTERS, character_changes
from rdx.musical.describe import describe

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def project():
    return starter_project()


@pytest.fixture
def selection(project):
    return {"track": next(t for t in project.tracks if t.role == "lead").id, "section": project.sections[2].id}


# --- character -------------------------------------------------------------


def test_warm_closes_the_filter_and_cuts_highs():
    changes = character_changes(Sound(preset="saw", cutoff=8000), "warm")
    assert changes["cutoff"] < 8000
    assert changes["high"] < 0
    assert changes["low"] > 0


def test_bright_is_the_opposite_of_warm():
    sound = Sound(preset="saw", cutoff=6000)
    assert character_changes(sound, "bright")["cutoff"] > 6000
    assert character_changes(sound, "warm")["cutoff"] < 6000


def test_intensity_scales_the_change_proportionally():
    sound = Sound(preset="saw", cutoff=8000)
    gentle = character_changes(sound, "warm", 0.25)["cutoff"]
    strong = character_changes(sound, "warm", 1.0)["cutoff"]
    assert 8000 > gentle > strong


def test_character_never_leaves_the_allowed_range():
    extreme = Sound(preset="saw", cutoff=20000, high=12, low=12, reverb=1, width=1)
    for word in CHARACTERS:
        for value in character_changes(extreme, word, 1.0).values():
            assert isinstance(value, float)
        updated = Sound.model_validate({**extreme.model_dump(), **character_changes(extreme, word, 1.0)})
        assert updated.cutoff <= 20000


def test_unknown_character_is_refused_not_guessed():
    with pytest.raises(KeyError):
        character_changes(Sound(), "sidechained")


def test_goosebumps_adds_width_flanger_and_panning():
    changes = character_changes(Sound(preset="supersaw"), "goosebumps", 1.0)
    assert changes["width"] > 0 and changes["flanger"] > 0 and changes["autopan"] > 0


# --- drums -----------------------------------------------------------------


def test_four_on_the_floor_puts_a_kick_on_every_beat():
    kicks = [n.start for n in drums.build(1, layers={"kick": "four_floor"}) if n.pitch == drums.KICK]
    assert kicks == [0.0, 1.0, 2.0, 3.0]


def test_double_clap_is_two_hits_a_thirty_second_apart_on_two_and_four():
    claps = [(n.start, n.velocity) for n in drums.build(1, layers={"clap": "double"}) if n.pitch == drums.CLAP]
    assert [c[0] for c in claps] == [1.0, 1.125, 3.0, 3.125]
    assert claps[1][1] < claps[0][1], "the second hit of a flam sits behind the first"


def test_kick_and_clap_layers_combine_independently():
    notes = drums.build(1, layers={"kick": "four_floor", "clap": "double"})
    assert {n.pitch for n in notes} == {drums.KICK, drums.CLAP}


def test_open_hats_land_offbeat_in_the_trance_kits():
    opens = [n.start for n in drums.build(1, "mainstage") if n.pitch == drums.OPEN]
    assert opens == [0.5, 1.5, 2.5, 3.5]


def test_low_density_thins_hats_but_never_the_kick():
    sparse = drums.build(1, "four_floor", density=0.2)
    busy = drums.build(1, "four_floor", density=0.9)
    assert len([n for n in sparse if n.pitch == drums.HAT]) < len([n for n in busy if n.pitch == drums.HAT])
    assert len([n for n in sparse if n.pitch == drums.KICK]) == 4


def test_snare_roll_accelerates_and_gets_louder():
    roll = drums.build_roll(4, 0)
    gaps = [round(b.start - a.start, 4) for a, b in zip(roll, roll[1:])]
    assert gaps[0] > gaps[-1], "the roll should speed up"
    assert roll[-1].velocity > roll[0].velocity, "the roll should build"


def test_every_drum_note_stays_inside_the_section():
    for bars in (1, 2, 8):
        for note in drums.build(bars, "mainstage", density=1.0, crash=True, fill=True):
            assert note.start + note.duration <= bars * 4 + 1e-9


def test_unknown_layer_or_pattern_is_refused():
    with pytest.raises(KeyError):
        drums.resolve(None, {"cowbell": "eighth"})
    with pytest.raises(ValueError):
        drums.resolve(None, {"clap": "triple"})


# --- harmony ---------------------------------------------------------------


def held(pitches, duration=3.5):
    return [Note(pitch=p, start=i * 4, duration=duration, velocity=90) for i, p in enumerate(pitches)]


def moving(bars_of_pitches):
    return [Note(pitch=p, start=bar * 4 + i, duration=0.9, velocity=90) for bar, row in enumerate(bars_of_pitches) for i, p in enumerate(row)]


def test_held_notes_are_read_as_chord_roots():
    assert harmony.looks_like_roots(held([57, 53, 60, 55]), 4)


def test_a_busy_line_is_read_as_a_melody():
    assert not harmony.looks_like_roots(moving([[69, 72, 76, 72]] * 4), 4)


def test_hummed_roots_become_the_progression_they_name():
    entries = harmony.progression(held([57, 53, 60, 55]), 4, "A", "minor")
    assert harmony.describe(entries) == "Am - F - C - G (i - VI - III - VII)"


def test_a_hummed_melody_gets_harmony_inferred_underneath():
    melody = moving([[69, 72, 76, 72], [65, 69, 72, 69], [72, 76, 79, 76], [67, 71, 74, 71]])
    entries = harmony.progression(melody, 4, "A", "minor")
    assert [c.symbol for _, _, c in entries] == ["Am", "F", "C", "G"]


def test_the_progression_covers_the_whole_section():
    entries = harmony.progression(held([57, 53]), 4, "A", "minor")
    assert entries[0][0] == 0.0
    assert entries[-1][0] + entries[-1][1] >= 16 - 1e-6


def test_voicing_moves_smoothly_between_chords():
    entries = harmony.progression(held([57, 53, 60, 55]), 4, "A", "minor")
    notes = harmony.voice(entries, voices=3)
    by_start: dict[float, list[int]] = {}
    for note in notes:
        by_start.setdefault(note.start, []).append(note.pitch)
    chords = [sorted(v) for _, v in sorted(by_start.items())]
    for previous, following in zip(chords, chords[1:]):
        movement = sum(abs(a - b) for a, b in zip(previous, following))
        assert movement <= 7, "voice leading should glide, not leap"


def test_voicing_stays_in_the_requested_register():
    entries = harmony.progression(held([57, 53, 60, 55]), 4, "A", "minor")
    for note in harmony.voice(entries, low=48, high=72, voices=3):
        assert 36 <= note.pitch <= 84


def test_minor_keys_offer_the_borrowed_major_dominant():
    symbols = [c.symbol for c in harmony.diatonic("A", "minor")]
    assert "Em" in symbols and "E" in symbols


# --- production moves ------------------------------------------------------


def test_buildup_opens_the_filter_across_the_section(project, selection):
    after = apply_actions(project, [Action(kind="move", section="Build", params={"name": "buildup", "riser": False, "roll": False})], selection)
    lead = next(t for t in after.tracks if t.role == "lead")
    lane = next(a for a in lead.automation if a.parameter == "cutoff")
    assert lane.points[0][1] < lane.points[-1][1], "the filter should rise"


def test_buildup_adds_a_riser_and_a_snare_roll(project, selection):
    after = apply_actions(project, [Action(kind="move", section="Build", params={"name": "buildup"})], selection)
    assert any(t.name == "Riser" for t in after.tracks)
    drum_track = next(t for t in after.tracks if t.role == "drums")
    build = next(s for s in after.sections if s.name == "Build")
    clip = next(c for c in drum_track.clips if c.section_id == build.id)
    snares = sorted(n.start for n in clip.notes if n.pitch == drums.SNARE)
    assert len(snares) > 8, "a buildup should end in a roll"


def test_a_buildup_cut_silences_everything_at_the_end(project, selection):
    after = apply_actions(project, [Action(kind="move", section="Build", params={"name": "buildup", "cut_bars": 1})], selection)
    build = next(s for s in after.sections if s.name == "Build")
    faded = [t for t in after.tracks if any(a.parameter == "volume_db" and a.section_id == build.id and a.points[-1][1] <= -60 for a in t.automation)]
    assert len(faded) >= 4, "everything should drop away together"


def test_buildup_refuses_a_cut_longer_than_the_section(project, selection):
    with pytest.raises(EditError):
        apply_actions(project, [Action(kind="move", section="Build", params={"name": "buildup", "cut_bars": 99})], selection)


def test_drop_clears_the_buildup_automation(project, selection):
    built = apply_actions(project, [Action(kind="move", section="Main", params={"name": "buildup", "riser": False})], selection)
    dropped = apply_actions(built, [Action(kind="move", section="Main", params={"name": "drop"})], selection)
    main = next(s for s in dropped.sections if s.name == "Main")
    lead = next(t for t in dropped.tracks if t.role == "lead")
    assert not [a for a in lead.automation if a.section_id == main.id and a.parameter == "cutoff"]


def test_layer_doubles_a_part_onto_a_new_sound(project, selection):
    after = apply_actions(project, [Action(kind="move", params={"name": "layer", "track": "lead", "preset": "supersaw", "layer_name": "Big Lead"})], selection)
    big = next(t for t in after.tracks if t.name == "Big Lead")
    lead = next(t for t in after.tracks if t.role == "lead" and t.name != "Big Lead")
    assert big.sound.preset == "supersaw"
    assert [n.pitch for c in big.clips for n in c.notes] == [n.pitch for c in lead.clips for n in c.notes]


def test_layer_an_octave_up_transposes_the_copy_only(project, selection):
    after = apply_actions(project, [Action(kind="move", params={"name": "layer", "track": "lead", "octave": 1, "layer_name": "Octave"})], selection)
    original = next(t for t in project.tracks if t.role == "lead")
    copy = next(t for t in after.tracks if t.name == "Octave")
    assert [n.pitch for c in copy.clips for n in c.notes] == [n.pitch + 12 for c in original.clips for n in c.notes]


def test_a_move_cannot_contain_another_move(project, selection):
    with pytest.raises(EditError, match="cannot contain another move"):
        apply_actions(project, [Action(kind="move", section="Main", params={"name": "buildup"})], selection, _depth=1)


def test_moves_respect_protected_tracks(project, selection):
    locked = apply_actions(project, [Action(kind="protect", track="drums", params={"locked": True})], selection)
    after = apply_actions(locked, [Action(kind="move", section="Build", params={"name": "buildup", "roll": False, "riser": False})], selection)
    drum_track = next(t for t in after.tracks if t.role == "drums")
    assert not drum_track.automation, "a protected track should be left alone"


# --- targeting -------------------------------------------------------------


def test_a_drum_request_finds_the_drum_track_without_being_told(project, selection):
    after = apply_actions(project, [Action(kind="kit", params={"kit": "mainstage"})], selection)
    main = next(s for s in after.sections if s.name == "Main")
    drum_track = next(t for t in after.tracks if t.role == "drums")
    assert any(c.section_id == main.id for c in drum_track.clips)


def test_the_word_selected_resolves_to_the_current_selection(project, selection):
    after = apply_actions(project, [Action(kind="character", track="selected", params={"character": "warm"})], selection)
    lead = next(t for t in after.tracks if t.id == selection["track"])
    assert lead.sound.cutoff < next(t for t in project.tracks if t.id == selection["track"]).sound.cutoff


def test_a_missing_target_names_the_real_options(project):
    with pytest.raises(EditError, match="Drums"):
        apply_actions(project, [Action(kind="character", params={"character": "warm"})], None)


def test_a_wrong_track_name_says_what_exists(project, selection):
    with pytest.raises(EditError, match="no track called"):
        apply_actions(project, [Action(kind="character", track="Guitar", params={"character": "warm"})], selection)


# --- refusing what RDX cannot do -------------------------------------------


@pytest.mark.parametrize(
    "action",
    [
        Action(kind="sound", track="lead", params={"preset": "vocoder"}),
        Action(kind="character", track="lead", params={"character": "sidechained"}),
        Action(kind="move", section="Main", params={"name": "tapestop"}),
        Action(kind="kit", params={"layers": {"cowbell": "eighth"}}),
    ],
)
def test_unsupported_requests_are_refused_by_name(project, selection, action):
    with pytest.raises(Unsupported):
        apply_actions(project, [action], selection)


def test_errors_never_leak_raw_validation_text(project, selection):
    for action in [
        Action(kind="sound", track="lead", params={"cutoff": 99999}),
        Action(kind="project", params={"tempo": 9000}),
        Action(kind="mix", track="bass", params={"pan": 40}),
    ]:
        with pytest.raises(EditError) as caught:
            apply_actions(project, [action], selection)
        assert "pydantic" not in str(caught.value) and "validation error" not in str(caught.value).lower()


# --- honest reporting ------------------------------------------------------


def test_the_description_reports_the_real_change_not_the_intent(project, selection):
    after = apply_actions(project, [Action(kind="character", track="lead", params={"character": "warm"})], selection)
    text = describe(project, after)
    assert "filter" in text and "Lead" in text


def test_nothing_changed_is_reported_as_nothing(project):
    assert describe(project, project.model_copy(deep=True)) == "Nothing changed."


def test_harmony_reports_the_progression_it_heard(project, selection):
    section = next(s for s in project.sections if s.name == "Main")
    strings = apply_actions(project, [Action(kind="add_track", params={"role": "chords", "name": "Strings", "preset": "strings"})], selection)
    track = next(t for t in strings.tracks if t.name == "Strings")
    track.clips.append(Clip(name="Hum", section_id=section.id, notes=held([57, 53, 60, 55])))
    findings: list[str] = []
    apply_actions(strings, [Action(kind="harmony", track="Strings", section="Main", params={})], selection, findings)
    assert "Am - F - C - G" in findings[0]


def test_the_kit_reports_which_layers_it_used(project, selection):
    findings: list[str] = []
    apply_actions(project, [Action(kind="kit", params={"layers": {"kick": "four_floor", "clap": "double"}})], selection, findings)
    assert "clap double" in findings[0] and "kick four_floor" in findings[0]


# --- the two languages must agree ------------------------------------------


def test_the_drum_map_matches_the_audio_engine():
    """Python decides the drum pitches; the browser must play the same ones."""
    source = (ROOT / "src/audio/drums.ts").read_text()
    block = re.search(r"export const DRUM_MAP[^=]*=\s*(\{.*?\})\s*;", source, re.S)
    assert block, "src/audio/drums.ts must export a DRUM_MAP"
    literal = re.sub(r"(\d+)\s*:", r'"\1":', block.group(1)).replace("'", '"')
    mirrored = json.loads(re.sub(r",\s*}", "}", literal))
    assert {int(k): v for k, v in mirrored.items()} == DRUM_MAP
