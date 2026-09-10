"""Tests for the musical knowledge RDX owns in code.

These assert musical results, not that a function returned. If a producer
disagrees with what "warm" or "buildup" means, the argument happens here.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from rdx.domain import Action, Clip, DRUM_MAP, Note, Sound
from rdx.engine import EditError, Unsupported, apply_actions, starter_project
from rdx.musical import drums, harmony, melody, moves, sidechain
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


# --- ducking ---------------------------------------------------------------


def four_kicks(bars=1):
    return [Note(pitch=drums.KICK, start=bar * 4 + beat, duration=0.12, velocity=100) for bar in range(bars) for beat in (0, 1, 2, 3)]


def gain_at(points, beat):
    """Read the ducking curve the way the audio engine will: linear between points."""
    for (a_beat, a_gain), (b_beat, b_gain) in zip(points, points[1:]):
        if a_beat <= beat <= b_beat:
            if b_beat - a_beat < 1e-9:
                return b_gain
            return a_gain + (b_gain - a_gain) * (beat - a_beat) / (b_beat - a_beat)
    return points[-1][1]


def test_the_level_falls_when_the_kick_lands_and_returns_before_the_next():
    points = sidechain.ducking_points(sidechain.trigger_beats(four_kicks(), "kick"), 4, amount=0.75, attack=0.02, release=0.9, curve="exponential")
    assert gain_at(points, 0.02) == pytest.approx(0.25, abs=0.01), "a quarter of the level under the kick"
    assert gain_at(points, 0.95) > 0.95, "and back up by the next beat"


def test_a_deeper_amount_ducks_further():
    shallow = sidechain.ducking_points([0.0], 4, amount=0.3, attack=0.02, release=0.9, curve="linear")
    deep = sidechain.ducking_points([0.0], 4, amount=0.9, attack=0.02, release=0.9, curve="linear")
    assert gain_at(deep, 0.02) < gain_at(shallow, 0.02)


def test_a_longer_release_is_still_down_where_a_short_one_has_recovered():
    short = sidechain.ducking_points([0.0], 8, amount=0.75, attack=0.02, release=0.35, curve="linear")
    long = sidechain.ducking_points([0.0], 8, amount=0.75, attack=0.02, release=1.9, curve="linear")
    assert gain_at(short, 0.5) > gain_at(long, 0.5)


def test_the_curve_never_leaves_the_audible_range():
    for name, shape in sidechain.SHAPES.items():
        points = sidechain.ducking_points(sidechain.trigger_beats(four_kicks(2), "kick"), 8, amount=shape.amount, attack=shape.attack, release=shape.release, curve=shape.curve)
        assert points[0][0] == 0.0 and points[-1][0] == 8.0, name
        assert all(0 <= gain <= 1 for _, gain in points), name
        assert all(b[0] >= a[0] for a, b in zip(points, points[1:])), f"{name} must move forwards in time"


def test_a_fast_pattern_cuts_the_recovery_short_instead_of_overlapping():
    points = sidechain.ducking_points([0.0, 0.5], 4, amount=0.8, attack=0.02, release=2.0, curve="linear")
    assert gain_at(points, 0.52) == pytest.approx(0.2, abs=0.01), "the second hit ducks from wherever it got to"


def test_only_the_named_drum_voice_triggers_the_duck():
    notes = four_kicks() + [Note(pitch=drums.HAT, start=0.5, duration=0.1, velocity=50)]
    assert sidechain.trigger_beats(notes, "kick") == [0.0, 1.0, 2.0, 3.0]
    assert 0.5 in sidechain.trigger_beats(notes, "all")


def test_a_flammed_clap_ducks_once_not_twice():
    claps = [Note(pitch=drums.CLAP, start=1.0, duration=0.1, velocity=96), Note(pitch=drums.CLAP, start=1.125, duration=0.1, velocity=74)]
    assert sidechain.trigger_beats(claps, "clap") == [1.0]


def test_no_source_notes_leaves_the_level_alone():
    assert sidechain.ducking_points([], 4, amount=0.9, attack=0.02, release=1, curve="linear") == [[0.0, 1.0], [4.0, 1.0]]


def test_depth_is_reported_in_decibels_a_producer_would_recognise():
    assert sidechain.depth_db(0.75) == -12.0
    assert sidechain.depth_db(0.5) == -6.0


def test_sidechain_defaults_to_the_kick_of_the_one_drum_track(project, selection):
    after = apply_actions(project, [Action(kind="sidechain", track="bass", params={"shape": "pump"})], selection)
    bass = next(t for t in after.tracks if t.role == "bass")
    drum_track = next(t for t in after.tracks if t.role == "drums")
    assert bass.sidechain.source == drum_track.id
    assert bass.sidechain.trigger == "kick"
    assert bass.sidechain.amount == sidechain.SHAPES["pump"].amount


def test_the_pump_move_ducks_every_instrument_but_not_the_drums(project, selection):
    after = apply_actions(project, [Action(kind="move", params={"name": "pump"})], selection)
    ducked = {t.role for t in after.tracks if t.sidechain}
    assert ducked == {"bass", "chords", "lead"}


def test_ducking_can_be_taken_off_again(project, selection):
    on = apply_actions(project, [Action(kind="move", params={"name": "pump"})], selection)
    off = apply_actions(on, [Action(kind="sidechain", track="bass", params={"operation": "remove"})], selection)
    assert next(t for t in off.tracks if t.role == "bass").sidechain is None


def test_a_track_cannot_duck_to_itself(project, selection):
    with pytest.raises(EditError):
        apply_actions(project, [Action(kind="sidechain", track="bass", params={"source": "bass"})], selection)


def test_removing_the_trigger_track_removes_the_ducking_with_it(project, selection):
    on = apply_actions(project, [Action(kind="move", params={"name": "pump"})], selection)
    after = apply_actions(on, [Action(kind="remove_track", track="drums", params={})], selection)
    assert not any(t.sidechain for t in after.tracks)


def test_ducking_reports_the_depth_it_actually_applied(project, selection):
    findings: list[str] = []
    after = apply_actions(project, [Action(kind="sidechain", track="bass", params={"shape": "pump"})], selection, findings)
    assert "12.0 dB" in findings[0]
    assert "12.0 dB" in describe(project, after)


def test_an_unknown_ducking_shape_is_refused_by_name(project, selection):
    with pytest.raises(Unsupported, match="pump"):
        apply_actions(project, [Action(kind="sidechain", track="bass", params={"shape": "squash"})], selection)


def test_ducking_to_a_recording_is_refused_rather_than_approximated(project, selection):
    with_audio = apply_actions(project, [Action(kind="add_track", params={"role": "audio", "name": "Vocal"})], selection)
    with pytest.raises(Unsupported, match="recording"):
        apply_actions(with_audio, [Action(kind="sidechain", track="bass", params={"source": "Vocal"})], selection)


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


def javascript_object(source: str, name: str) -> dict:
    """Read one exported object literal out of a TypeScript file as JSON."""
    block = re.search(rf"export const {name}[^=]*=\s*(\{{.*?\n\}})\s*;", source, re.S)
    assert block, f"the audio engine must export {name}"
    literal = re.sub(r"(\w+)\s*:", r'"\1":', block.group(1)).replace("'", '"')
    return json.loads(re.sub(r",(\s*[}\]])", r"\1", literal))


def test_the_ducking_shapes_match_the_audio_engine():
    """Python decides what a pump is; the browser must play the same curve."""
    source = (ROOT / "src/audio/sidechain.ts").read_text()
    mirrored = javascript_object(source, "SHAPES")
    assert set(mirrored) == set(sidechain.SHAPES)
    for name, shape in sidechain.SHAPES.items():
        assert mirrored[name] == {"amount": shape.amount, "release": shape.release, "attack": shape.attack, "curve": shape.curve}, name
    triggers = javascript_object(source, "TRIGGERS")
    assert triggers == sidechain.TRIGGERS


CROSS_CHECK = """
import { duckingPoints, SHAPES, triggerBeats } from "%s";
const notes = [];
for (let bar = 0; bar < 2; bar++)
  for (const beat of [0, 1, 2, 3])
    notes.push({ pitch: 36, start: bar * 4 + beat, duration: 0.12, velocity: 100 });
const out = {};
for (const [name, shape] of Object.entries(SHAPES))
  out[name] = duckingPoints(triggerBeats(notes, "kick"), 8, shape);
out.crowded = duckingPoints([0, 0.5, 0.75], 4, { amount: 0.8, attack: 0.02, release: 2, curve: "linear" });
console.log(JSON.stringify(out));
"""


def test_the_ducking_curve_is_identical_in_both_languages(tmp_path):
    """The table matching is not enough; the arithmetic must agree too.

    Rounding is the trap here: Python rounds halves to even and JavaScript
    rounds them up, which silently moves points apart. This runs the real
    TypeScript and compares every point.
    """
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    script = tmp_path / "cross-check.mjs"
    script.write_text(CROSS_CHECK % (ROOT / "src/audio/sidechain.ts"))
    result = subprocess.run([node, "--experimental-strip-types", str(script)], capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stderr
    mirrored = json.loads(result.stdout)

    kicks = [Note(pitch=drums.KICK, start=bar * 4 + beat, duration=0.12, velocity=100) for bar in range(2) for beat in (0, 1, 2, 3)]
    beats = sidechain.trigger_beats(kicks, "kick")
    for name, shape in sidechain.SHAPES.items():
        assert sidechain.ducking_points(beats, 8, amount=shape.amount, attack=shape.attack, release=shape.release, curve=shape.curve) == mirrored[name], name
    assert sidechain.ducking_points([0.0, 0.5, 0.75], 4, amount=0.8, attack=0.02, release=2.0, curve="linear") == mirrored["crowded"]


# --- phrase shape ----------------------------------------------------------


def line(pitches, step=0.5, duration=0.4):
    return [Note(pitch=p, start=round(i * step, 4), duration=duration, velocity=90) for i, p in enumerate(pitches)]


def test_making_space_removes_notes_and_keeps_the_downbeats():
    busy = line([69, 71, 72, 74, 76, 74, 72, 71])
    spaced = melody.space(busy, amount=0.5, length=4)
    assert len(spaced) < len(busy)
    assert any(abs(n.start) < 1e-6 for n in spaced), "the downbeat must survive"
    assert sum(n.duration for n in spaced) > sum(n.duration for n in busy) / 2, "survivors are held longer"


def test_making_space_never_lets_a_note_run_past_the_next_one():
    spaced = melody.space(line([69, 71, 72, 74, 76, 74]), amount=0.34, length=3)
    for first, second in zip(spaced, spaced[1:]):
        assert first.start + first.duration <= second.start + 1e-6


def test_filling_adds_notes_that_stay_in_the_key():
    sparse = line([69, 76, 72, 74], step=1.0, duration=0.4)
    filled = melody.fill(sparse, amount=1.0, key="A", scale="minor", length=4)
    assert len(filled) > len(sparse)
    for note in filled:
        assert (note.pitch - 9) % 12 in melody.MINOR, "A minor has no notes outside its scale"


def test_a_rising_shape_lifts_the_end_and_leaves_the_opening_alone():
    phrase = line([69] * 8)
    risen = melody.shape(phrase, "rise", degrees=3, key="A", scale="minor", length=4)
    assert risen[0].pitch == 69, "the first note is the idea; it stays"
    assert risen[-1].pitch > risen[0].pitch, "the phrase should climb"
    assert [n.pitch for n in risen] == sorted(n.pitch for n in risen), "and climb steadily"


def test_a_falling_shape_is_the_mirror_of_a_rising_one():
    phrase = line([69] * 8)
    assert melody.shape(phrase, "fall", degrees=3, length=4)[-1].pitch < melody.shape(phrase, "rise", degrees=3, length=4)[-1].pitch


def test_an_arch_goes_up_and_comes_back():
    arched = melody.shape(line([69] * 9), "arch", degrees=4, length=4.5)
    middle = arched[len(arched) // 2].pitch
    assert middle > arched[0].pitch and middle > arched[-1].pitch


def test_reshaping_a_phrase_never_leaves_the_key():
    for name in melody.CONTOURS:
        for note in melody.shape(line([69, 72, 76, 74, 71, 69, 67, 72]), name, degrees=5, key="F", scale="major", length=4):
            assert (note.pitch - 5) % 12 in melody.MAJOR, name


def bars_of(*bars):
    """Notes on the beat, a bar at a time, so repeats line up exactly."""
    return [Note(pitch=p, start=float(bar * 4 + beat), duration=0.4, velocity=90) for bar, pitches in enumerate(bars) for beat, p in enumerate(pitches)]


def test_repetition_is_measured_not_guessed():
    assert melody.repetition(bars_of([69, 72, 76, 72], [69, 72, 76, 72]), 2) == 1.0
    assert melody.repetition(bars_of([69, 72, 76, 72], [71, 74, 77, 74]), 2) == 0.0


def test_varying_changes_the_repeats_and_protects_the_first_statement():
    notes = bars_of(*([[69, 72, 76, 72]] * 4))
    varied = melody.vary(notes, 4, key="A", scale="minor", amount=1.0, seed=5)
    assert [n.pitch for n in varied[:4]] == [69, 72, 76, 72], "the opening bar is the idea"
    assert melody.repetition(varied, 4) < melody.repetition(notes, 4)


def test_an_unknown_phrase_shape_is_refused_by_name(project, selection):
    with pytest.raises(Unsupported, match="arch"):
        apply_actions(project, [Action(kind="phrase", track="lead", section="Main", params={"shape": "zigzag"})], selection)


def test_shaping_a_phrase_through_the_engine_keeps_it_inside_the_section(project, selection):
    after = apply_actions(project, [Action(kind="phrase", track="lead", section="Main", params={"operation": "fill", "amount": 1.0})], selection)
    main = next(s for s in after.sections if s.name == "Main")
    clip = next(c for c in next(t for t in after.tracks if t.role == "lead").clips if c.section_id == main.id)
    assert clip.notes and all(n.start + n.duration <= main.bars * 4 + 1e-9 for n in clip.notes)


def test_phrase_shaping_is_refused_on_drums(project, selection):
    with pytest.raises(EditError, match="melodic"):
        apply_actions(project, [Action(kind="phrase", track="drums", section="Main", params={"operation": "space"})], selection)


def test_the_phrase_report_says_what_it_did(project, selection):
    findings: list[str] = []
    apply_actions(project, [Action(kind="phrase", track="lead", section="Main", params={"operation": "space", "amount": 0.5})], selection, findings)
    assert "notes" in findings[0] and "Lead" in findings[0]
