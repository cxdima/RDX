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

from rdx.domain import Action, AUTOMATABLE, AUTOMATION_RANGES, Clip, DRUM_MAP, Kit, LFO_TARGETS, Note, SCALES, SCALE_STEPS, Sound, WAVES
from rdx.engine import EditError, Unsupported, apply_actions, starter_project
from rdx.musical import design, drums, harmony, melody, moves, parts, sidechain
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


@pytest.mark.parametrize("intensity", [0.15, 0.37, 0.6, 1.0])
def test_character_never_produces_a_sound_the_model_refuses(intensity):
    """Every word, at every strength, from an extreme starting point."""
    extreme = Sound(preset="saw", cutoff=20000, high=12, low=12, reverb=1, width=1, unison=7, sustain=1)
    for word in CHARACTERS:
        changes = character_changes(extreme, word, intensity)
        for name, value in changes.items():
            field = Sound.model_fields[name]
            assert isinstance(value, str if field.annotation not in (float, int) else (int, float)), f"{word}.{name}"
        updated = Sound.model_validate({**extreme.model_dump(), **changes})
        assert updated.cutoff <= 20000 and 1 <= updated.unison <= 7


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


# --- richer harmony --------------------------------------------------------


def progression_of(pitches, key="A", scale="minor"):
    return harmony.progression(held(pitches), len(pitches), key, scale)


def test_the_seventh_comes_from_the_key_not_from_the_triad():
    """In A minor the VII is G7 and the III is Cmaj7, and both are major triads."""
    coloured = harmony.colour_progression(progression_of([57, 53, 60, 55]), "seventh", "minor")
    assert [c.symbol for _, _, c in coloured] == ["Am7", "Fmaj7", "Cmaj7", "G7"]


def test_the_dominant_of_a_major_key_takes_a_flat_seventh():
    coloured = harmony.colour_progression(progression_of([60, 67, 65, 60], "C", "major"), "seventh", "major")
    assert [c.symbol for _, _, c in coloured] == ["Cmaj7", "G7", "Fmaj7", "Cmaj7"]


def test_every_colour_stays_inside_the_key_except_the_one_that_says_it_does_not():
    scale_pcs = {(9 + step) % 12 for step in harmony.MINOR}
    for colour in harmony.COLOURS:
        outside = {pc for _, _, chord in harmony.colour_progression(progression_of([57, 53, 60, 55]), colour, "minor") for pc in chord.pitch_classes} - scale_pcs
        assert bool(outside) == (colour in harmony.BORROWS), f"{colour} put {outside} outside the key"


def test_the_borrowed_sixth_is_reported_rather_than_slipped_in(project, selection):
    section = next(s for s in project.sections if s.name == "Main")
    with_source = apply_actions(project, [Action(kind="add_track", params={"role": "chords", "name": "Keys"})], selection)
    next(t for t in with_source.tracks if t.name == "Keys").clips.append(Clip(name="Hum", section_id=section.id, notes=held([57, 53, 60, 55])))
    findings: list[str] = []
    apply_actions(with_source, [Action(kind="harmony", track="Keys", section="Main", params={"colour": "sixth"})], selection, findings)
    assert any("Dorian" in line for line in findings)


def test_a_colour_can_be_taken_back_off_again():
    plain = progression_of([57, 53, 60, 55])
    sevenths = harmony.colour_progression(plain, "seventh", "minor")
    assert [c.symbol for _, _, c in harmony.colour_progression(sevenths, "plain", "minor")] == [c.symbol for _, _, c in plain]


def melody_of(pairs):
    """A moving line of (pitch, duration), laid end to end."""
    notes, start = [], 0.0
    for pitch_value, duration in pairs:
        notes.append(Note(pitch=pitch_value, start=round(start, 4), duration=duration, velocity=90))
        start += duration
    return notes


def test_a_melody_that_leans_on_the_fourth_and_never_plays_the_third_is_heard_as_sus4():
    # A, D and E over an A root, with no C anywhere: that is Asus4, not Am.
    chosen = harmony.progression(melody_of([(69, 1.5), (62, 0.7), (69, 1.0), (64, 0.5), (62, 0.3)]), 1, "A", "minor")[0][2]
    assert chosen.symbol == "Asus4", chosen.symbol


def test_the_same_melody_with_the_third_in_it_is_a_plain_triad():
    chosen = harmony.progression(melody_of([(69, 1.5), (60, 0.7), (69, 1.0), (64, 0.5), (60, 0.3)]), 1, "A", "minor")[0][2]
    assert chosen.quality in harmony.TRIADS, chosen.symbol


def test_a_degree_whose_fourth_is_a_tritone_is_never_suspended():
    """The fourth above the VI of a minor key is not a suspension at all."""
    sixth_degree = next(c for c in harmony.diatonic("A", "minor") if c.degree == 5)
    assert sixth_degree.coloured("sus4", "minor").quality in harmony.TRIADS


def test_asking_for_sevenths_widens_the_voicing_to_carry_them(project, selection):
    section = next(s for s in project.sections if s.name == "Main")
    with_source = apply_actions(project, [Action(kind="add_track", params={"role": "chords", "name": "Keys", "preset": "strings"})], selection)
    keys_track = next(t for t in with_source.tracks if t.name == "Keys")
    keys_track.clips.append(Clip(name="Hum", section_id=section.id, notes=held([57, 53, 60, 55])))
    after = apply_actions(with_source, [Action(kind="harmony", track="Keys", section="Main", params={"colour": "seventh"})], selection)
    clip = next(c for c in next(t for t in after.tracks if t.name == "Keys").clips if c.section_id == section.id)
    at_start = [n.pitch for n in clip.notes if abs(n.start) < 1e-6]
    assert len(at_start) == 4, "a seventh chord nobody can hear is not a seventh chord"


def test_an_unknown_chord_colour_is_refused_by_name(project, selection):
    section = next(s for s in project.sections if s.name == "Main")
    with_source = apply_actions(project, [Action(kind="add_track", params={"role": "chords", "name": "Keys"})], selection)
    next(t for t in with_source.tracks if t.name == "Keys").clips.append(Clip(name="Hum", section_id=section.id, notes=held([57, 53])))
    with pytest.raises(Unsupported, match="seventh"):
        apply_actions(with_source, [Action(kind="harmony", track="Keys", section="Main", params={"colour": "lydian"})], selection)


# --- one part written against another --------------------------------------


def chords_of(*roots):
    """Held triads, one per bar, the way the chord track actually looks."""
    return [Note(pitch=root + interval, start=float(bar * 4), duration=3.8, velocity=74) for bar, root in enumerate(roots) for interval in (0, 3, 7)]


def test_a_following_bass_lands_on_the_root_of_every_chord():
    written = parts.follow(chords_of(57, 53, 60, 55), 16, role="bass")
    assert [n.pitch % 12 for n in written] == [57 % 12, 53 % 12, 60 % 12, 55 % 12]
    assert all(28 <= n.pitch <= 52 for n in written), "a bass part belongs in the bass register"


def test_following_can_keep_the_rhythm_it_already_had():
    # Eight beats of eighth notes, so the groove spans both chords.
    groove = [Note(pitch=45, start=b * 0.5, duration=0.4, velocity=90) for b in range(16)]
    written = parts.follow(chords_of(57, 53), 8, role="bass", rhythm=groove)
    assert [n.start for n in written] == [n.start for n in groove], "the groove is what was kept"
    assert {n.pitch % 12 for n in written} == {9, 5}, "but the notes follow the chords"


def test_a_counter_rhythm_lands_where_the_other_part_is_silent():
    kick = [Note(pitch=36, start=float(b), duration=0.12, velocity=100) for b in range(4)]
    written = parts.counter(kick, 4, grid=0.5, density=1.0, key="A", scale="minor", seed=1)
    assert written
    for note in written:
        assert all(abs(note.start - hit.start) > 1e-6 for hit in kick), "a counter-rhythm answers, it does not double"


def test_a_harmony_line_moves_in_scale_degrees_not_semitones():
    melody_line = [Note(pitch=p, start=float(i), duration=0.9, velocity=90) for i, p in enumerate([69, 71, 72, 74])]
    line = parts.harmonise(melody_line, degrees=2, key="A", scale="minor")
    intervals = [b.pitch - a.pitch for a, b in zip(melody_line, line)]
    assert set(intervals) <= {3, 4}, "a third in the key is sometimes three semitones and sometimes four"
    assert len(set(intervals)) > 1, "a constant interval would be the wrong note somewhere"


def test_relating_the_bass_to_the_chords_through_the_engine(project, selection):
    after = apply_actions(project, [Action(kind="relate", track="bass", section="Main", params={"operation": "follow", "from_track": "chords"})], selection)
    main = next(s for s in after.sections if s.name == "Main")
    chords = next(c for c in next(t for t in after.tracks if t.role == "chords").clips if c.section_id == main.id)
    bass = next(c for c in next(t for t in after.tracks if t.role == "bass").clips if c.section_id == main.id)
    for note in bass.notes:
        sounding = [n.pitch % 12 for n in chords.notes if n.start <= note.start + 1e-6 < n.start + n.duration]
        assert not sounding or note.pitch % 12 in sounding, "the bass should be playing a note from the chord"


def test_a_part_cannot_be_written_against_itself(project, selection):
    with pytest.raises(EditError, match="itself"):
        apply_actions(project, [Action(kind="relate", track="bass", section="Main", params={"from_track": "bass"})], selection)


def test_an_unknown_relationship_is_refused_by_name(project, selection):
    with pytest.raises(Unsupported, match="follow"):
        apply_actions(project, [Action(kind="relate", track="bass", section="Main", params={"operation": "imitate", "from_track": "chords"})], selection)


def test_a_counter_rhythm_to_a_kit_answers_the_kick_rather_than_failing(project, selection):
    """A full kit leaves no gaps; naming no voice must still do the right thing."""
    after = apply_actions(project, [Action(kind="relate", track="lead", section="Main", params={"operation": "counter", "from_track": "drums", "density": 1.0})], selection)
    main = next(s for s in after.sections if s.name == "Main")
    clip = next(c for c in next(t for t in after.tracks if t.role == "lead").clips if c.section_id == main.id)
    assert clip.notes and all(n.start + n.duration <= main.bars * 4 + 1e-9 for n in clip.notes)


# --- the wider move library ------------------------------------------------


def test_a_transition_sweeps_out_leaves_a_gap_and_crashes_in(project, selection):
    after = apply_actions(project, [Action(kind="move", section="Build", params={"name": "transition"})], selection)
    build = next(s for s in after.sections if s.name == "Build")
    main = next(s for s in after.sections if s.name == "Main")
    lead = next(t for t in after.tracks if t.role == "lead")
    sweep = next(a for a in lead.automation if a.parameter == "cutoff" and a.section_id == build.id)
    assert sweep.points[-1][1] > sweep.points[0][1], "the filters open into the join"
    level = next(a for a in lead.automation if a.parameter == "volume_db" and a.section_id == build.id)
    assert level.points[-1][1] <= -60, "and everything drops for the gap"
    kit = next(t for t in after.tracks if t.role == "drums")
    crashes = [n for c in kit.clips if c.section_id == main.id for n in c.notes if n.pitch == drums.CRASH]
    assert crashes and crashes[0].start == 0.0, "the next section starts on a crash"


def test_a_riser_is_its_own_move_and_reuses_its_own_track(project, selection):
    once = apply_actions(project, [Action(kind="move", section="Build", params={"name": "riser"})], selection)
    twice = apply_actions(once, [Action(kind="move", section="Main", params={"name": "riser"})], selection)
    assert len([t for t in twice.tracks if t.name == "Riser"]) == 1, "one riser track, not one per use"
    riser = next(t for t in twice.tracks if t.name == "Riser")
    assert {a.section_id for a in riser.automation} == {s.id for s in twice.sections if s.name in {"Build", "Main"}}


def test_a_riser_over_part_of_a_section_starts_late(project, selection):
    after = apply_actions(project, [Action(kind="move", section="Main", params={"name": "riser", "bars": 2})], selection)
    main = next(s for s in after.sections if s.name == "Main")
    clip = next(c for c in next(t for t in after.tracks if t.name == "Riser").clips if c.section_id == main.id)
    assert clip.notes[0].start == main.bars * 4 - 8, "two bars of riser at the end of an eight bar section"


def test_double_time_keeps_the_tempo_and_doubles_the_part(project, selection):
    after = apply_actions(project, [Action(kind="move", section="Main", params={"name": "double_time", "roles": ["drums"]})], selection)
    assert after.tempo == project.tempo, "double time is a feel, not a tempo change"
    main = next(s for s in after.sections if s.name == "Main")
    before = next(c for c in next(t for t in project.tracks if t.role == "drums").clips if c.section_id == main.id)
    now = next(c for c in next(t for t in after.tracks if t.role == "drums").clips if c.section_id == main.id)
    assert len(now.notes) > len(before.notes)
    kicks_before = sorted(n.start for n in before.notes if n.pitch == drums.KICK)
    kicks_after = sorted(n.start for n in now.notes if n.pitch == drums.KICK)
    assert len(kicks_after) >= 2 * len(kicks_before) - 1, "twice as many kicks in the same span"


def test_half_time_thins_the_part_out(project, selection):
    after = apply_actions(project, [Action(kind="move", section="Main", params={"name": "double_time", "factor": 0.5, "roles": ["drums"]})], selection)
    main = next(s for s in after.sections if s.name == "Main")
    before = next(c for c in next(t for t in project.tracks if t.role == "drums").clips if c.section_id == main.id)
    now = next(c for c in next(t for t in after.tracks if t.role == "drums").clips if c.section_id == main.id)
    assert len(now.notes) < len(before.notes)


def test_every_move_stays_inside_its_section(project, selection):
    for name in moves.MOVES:
        if name in moves.WHOLE_TRACK_MOVES or name == "layer":
            continue
        after = apply_actions(project, [Action(kind="move", section="Main", params={"name": name})], selection)
        main = next(s for s in after.sections if s.name == "Main")
        for track in after.tracks:
            for clip in track.clips:
                if clip.section_id == main.id:
                    assert all(n.start + n.duration <= main.bars * 4 + 1e-6 for n in clip.notes), name


def test_an_unknown_move_is_refused_by_name(project, selection):
    with pytest.raises(Unsupported, match="transition"):
        apply_actions(project, [Action(kind="move", section="Main", params={"name": "tapestop"})], selection)


def test_a_stutter_retriggers_the_end_and_speeds_up(project, selection):
    after = apply_actions(project, [Action(kind="move", section="Main", params={"name": "stutter", "beats": 2, "tracks": ["lead"]})], selection)
    main = next(s for s in after.sections if s.name == "Main")
    clip = next(c for c in next(t for t in after.tracks if t.role == "lead").clips if c.section_id == main.id)
    window = sorted(n.start for n in clip.notes if n.start >= main.bars * 4 - 2)
    gaps = [round(b - a, 4) for a, b in zip(window, window[1:]) if b > a + 1e-9]
    assert gaps, "the window should be full of repeats"
    assert gaps[-1] <= gaps[0], "and they should get closer together"
    assert all(n.start + n.duration <= main.bars * 4 + 1e-9 for n in clip.notes)


def test_a_stutter_leaves_the_rest_of_the_section_alone(project, selection):
    after = apply_actions(project, [Action(kind="move", section="Main", params={"name": "stutter", "beats": 2, "tracks": ["lead"]})], selection)
    main = next(s for s in after.sections if s.name == "Main")
    before = next(c for c in next(t for t in project.tracks if t.role == "lead").clips if c.section_id == main.id)
    now = next(c for c in next(t for t in after.tracks if t.role == "lead").clips if c.section_id == main.id)
    limit = main.bars * 4 - 2
    assert [(n.pitch, n.start) for n in before.notes if n.start < limit] == [(n.pitch, n.start) for n in now.notes if n.start < limit]


def test_a_stutter_repeats_one_slice_rather_than_inventing_notes(project, selection):
    after = apply_actions(project, [Action(kind="move", section="Main", params={"name": "stutter", "beats": 2, "tracks": ["lead"]})], selection)
    main = next(s for s in after.sections if s.name == "Main")
    before = next(c for c in next(t for t in project.tracks if t.role == "lead").clips if c.section_id == main.id)
    now = next(c for c in next(t for t in after.tracks if t.role == "lead").clips if c.section_id == main.id)
    repeated = {n.pitch for n in now.notes if n.start >= main.bars * 4 - 2}
    assert repeated <= {n.pitch for n in before.notes}, "every note in the stutter was already in the part"


# --- sound design ----------------------------------------------------------


def test_every_patch_is_a_sound_the_engine_can_actually_make(project, selection):
    for name, patch in design.PATCHES.items():
        role = patch.roles[0]
        track_name = f"Test {name}"
        added = apply_actions(project, [Action(kind="add_track", params={"role": role, "name": track_name})], selection)
        after = apply_actions(added, [Action(kind="sound", track=track_name, params={"patch": name})], selection)
        sound = next(t for t in after.tracks if t.name == track_name).sound
        for field, value in patch.settings.items():
            assert getattr(sound, field) == value, f"{name}.{field}"


def test_a_patch_replaces_the_whole_sound_rather_than_blending_into_it(project, selection):
    dirty = apply_actions(project, [Action(kind="sound", track="lead", params={"flanger": 0.9, "phaser": 0.8, "reverb": 0.9})], selection)
    clean = apply_actions(dirty, [Action(kind="sound", track="lead", params={"patch": "pluck_stab"})], selection)
    sound = next(t for t in clean.tracks if t.role == "lead").sound
    assert sound.flanger == 0 and sound.phaser == 0, "a named sound is a whole sound, not a layer on the last one"


def test_settings_named_beside_a_patch_still_win(project, selection):
    after = apply_actions(project, [Action(kind="sound", track="lead", params={"patch": "pluck_stab", "reverb": 0.8})], selection)
    assert next(t for t in after.tracks if t.role == "lead").sound.reverb == 0.8


def test_a_patch_on_the_wrong_kind_of_track_is_refused_with_the_reason(project, selection):
    with pytest.raises(EditError, match="belongs on"):
        apply_actions(project, [Action(kind="sound", track="bass", params={"patch": "glass_pad"})], selection)


def test_a_patch_that_does_not_exist_is_refused_by_name(project, selection):
    with pytest.raises(Unsupported, match="reese"):
        apply_actions(project, [Action(kind="sound", track="lead", params={"patch": "moog"})], selection)


def test_a_preset_carries_its_own_envelope(project):
    """A pluck is a pluck because of how it decays, not because of its wave."""
    lead = next(t for t in project.tracks if t.role == "lead")
    assert lead.sound.preset == "pluck"
    assert lead.sound.sustain < 0.2 and lead.sound.decay < 0.25


def test_changing_the_preset_brings_its_envelope_with_it(project, selection):
    after = apply_actions(project, [Action(kind="sound", track="lead", params={"preset": "pad"})], selection)
    sound = next(t for t in after.tracks if t.role == "lead").sound
    assert sound.sustain > 0.5 and sound.attack > 0.2, "a pad does not keep a pluck's envelope"


def test_plucky_and_sustained_are_opposites_of_each_other():
    sound = Sound(preset="saw", decay=0.5, sustain=0.6)
    assert character_changes(sound, "plucky")["sustain"] < 0.6
    assert character_changes(sound, "sustained")["sustain"] > 0.6


def test_acidic_opens_the_filter_envelope_and_closes_the_filter():
    changes = character_changes(Sound(preset="saw", cutoff=8000), "acidic", 1.0)
    assert changes["filter_env"] > 0.5, "the envelope is what makes it acid"
    assert changes["cutoff"] < 8000 and changes["resonance"] > 1


def test_wobbling_points_the_lfo_at_the_filter_and_still_takes_it_off_again():
    on = character_changes(Sound(preset="saw"), "wobbling", 1.0)
    assert on["lfo_target"] == "cutoff" and on["lfo_depth"] > 0.5
    wobbling = Sound.model_validate({**Sound(preset="saw").model_dump(), **on})
    off = character_changes(wobbling, "still", 1.0)
    assert off["lfo_target"] == "off" and off["lfo_depth"] == 0


def test_stacked_stays_on_a_whole_number_of_voices():
    for intensity in (0.2, 0.45, 0.66, 0.9):
        changes = character_changes(Sound(preset="saw", unison=1), "stacked", intensity)
        assert isinstance(changes["unison"], int), "there is no such thing as 4.6 voices"


def test_the_patch_is_reported_in_the_producer_s_own_words(project, selection):
    findings: list[str] = []
    apply_actions(project, [Action(kind="sound", track="bass", params={"patch": "reese"})], selection, findings)
    assert "reese" in findings[0] and "detuned" in findings[0]


def test_the_patch_list_in_the_studio_matches_the_one_in_python():
    """A sound offered in the picker that RDX does not have is a refusal."""
    source = (ROOT / "src/App.tsx").read_text()
    block = re.search(r"const PATCHES = \[(.*?)\n\];", source, re.S)
    assert block, "src/App.tsx must list the patches it offers"
    listed = {
        name: set(re.findall(r'"(\w+)"', roles))
        for name, roles in re.findall(r'\{\s*name:\s*"(\w+)",\s*roles:\s*\[([^\]]*)\]', block.group(1))
    }
    assert listed == {name: set(patch.roles) for name, patch in design.PATCHES.items()}


def test_the_waveforms_and_lfo_targets_match_the_model():
    source = (ROOT / "src/App.tsx").read_text()
    for constant, expected in (("WAVES", WAVES), ("LFO_TARGETS", LFO_TARGETS)):
        block = re.search(rf"const {constant} = \[(.*?)\];", source, re.S)
        assert block, constant
        assert tuple(re.findall(r'"([\w]+)"', block.group(1))) == expected


# --- drum voices -----------------------------------------------------------


def test_every_drum_machine_is_a_kit_the_engine_can_make(project, selection):
    for name, machine in design.DRUM_KITS.items():
        after = apply_actions(project, [Action(kind="kit_sound", track="drums", params={"machine": name})], selection)
        kit = next(t for t in after.tracks if t.role == "drums").kit
        for field, value in machine.settings.items():
            assert getattr(kit, field) == value, f"{name}.{field}"


def test_an_808_kick_rings_much_longer_than_a_909(project, selection):
    def kick_decay(machine):
        after = apply_actions(project, [Action(kind="kit_sound", track="drums", params={"machine": machine})], selection)
        return next(t for t in after.tracks if t.role == "drums").kit.kick_decay

    assert kick_decay("808") > kick_decay("909") * 2, "that tail is the whole difference"


def test_a_drum_machine_replaces_the_voices_but_a_named_setting_still_wins(project, selection):
    after = apply_actions(project, [Action(kind="kit_sound", track="drums", params={"machine": "909", "kick_decay": 0.8})], selection)
    kit = next(t for t in after.tracks if t.role == "drums").kit
    assert kit.kick_decay == 0.8 and kit.hat_tone == design.DRUM_KITS["909"].settings["hat_tone"]


def test_tweaking_one_voice_leaves_the_rest_of_the_kit_alone(project, selection):
    eight = apply_actions(project, [Action(kind="kit_sound", track="drums", params={"machine": "808"})], selection)
    after = apply_actions(eight, [Action(kind="kit_sound", track="drums", params={"kick_tune": 3})], selection)
    kit = next(t for t in after.tracks if t.role == "drums").kit
    assert kit.kick_tune == 3 and kit.kick_decay == design.DRUM_KITS["808"].settings["kick_decay"]


def test_drum_voices_only_exist_on_drum_tracks(project, selection):
    with pytest.raises(EditError, match="not a drum track"):
        apply_actions(project, [Action(kind="kit_sound", track="lead", params={"kick_tune": 2})], selection)


def test_an_unknown_drum_machine_is_refused_by_name(project, selection):
    with pytest.raises(Unsupported, match="909"):
        apply_actions(project, [Action(kind="kit_sound", track="drums", params={"machine": "linndrum"})], selection)


def test_the_studio_starts_from_the_same_drum_voices_as_python():
    """The browser's defaults are what an untouched kit sounds like."""
    source = (ROOT / "src/audio/drums.ts").read_text()
    block = re.search(r"export const DEFAULT_KIT: Kit = (\{.*?\n\});", source, re.S)
    assert block, "src/audio/drums.ts must export DEFAULT_KIT"
    literal = re.sub(r"(\w+):", r'"\1":', block.group(1))
    mirrored = json.loads(re.sub(r",(\s*[}\]])", r"\1", literal))
    assert mirrored == {name: getattr(Kit(), name) for name in Kit.model_fields}


# --- progressions asked for rather than hummed ------------------------------


def test_a_named_progression_is_the_one_it_says_it_is():
    assert harmony.describe(harmony.named("trance", 4, "A", "minor")) == "Am - F - C - G (i - VI - III - VII)"
    assert harmony.describe(harmony.named("andalusian", 4, "A", "minor")) == "Am - G - F - E (i - VII - VI - V)"


def test_a_progression_transposes_with_the_key():
    in_a = [c.numeral for _, _, c in harmony.named("trance", 4, "A", "minor")]
    in_f = [c.numeral for _, _, c in harmony.named("trance", 4, "F", "minor")]
    assert in_a == in_f, "the degrees are the progression; the key only moves it"
    assert {c.root_pc for _, _, c in harmony.named("trance", 4, "A", "minor")} != {c.root_pc for _, _, c in harmony.named("trance", 4, "F", "minor")}


def test_roman_numerals_and_plain_numbers_both_read():
    assert harmony.parse_progression("i-VI-III-VII") == [0, 5, 2, 6]
    assert harmony.parse_progression("1 6 3 7") == [0, 5, 2, 6]
    assert harmony.parse_progression("I, IV, V, I") == [0, 3, 4, 0]


def test_a_nonsense_progression_is_refused_with_what_is_allowed():
    with pytest.raises(ValueError, match="I to VII"):
        harmony.parse_progression("i-IX-III")
    with pytest.raises(ValueError, match="two and sixteen"):
        harmony.parse_progression("i")


def test_a_progression_repeats_to_fill_the_section():
    entries = harmony.from_degrees([0, 5], 4, "A", "minor", span=4)
    assert len(entries) == 4, "two chords over four bars is the pair played twice"
    assert entries[0][2].degree == entries[2][2].degree


def test_chords_can_be_asked_for_without_humming_anything(project, selection):
    findings: list[str] = []
    after = apply_actions(project, [Action(kind="harmony", track="chords", section="Main", params={"progression": "trance"})], selection, findings)
    main = next(s for s in after.sections if s.name == "Main")
    clip = next(c for c in next(t for t in after.tracks if t.role == "chords").clips if c.section_id == main.id)
    assert clip.notes and "Am - F - C - G" in findings[0]


def test_an_empty_track_with_no_progression_named_says_what_to_do_instead(project, selection):
    with pytest.raises(EditError, match="Name a progression instead"):
        apply_actions(project, [Action(kind="harmony", track="lead", section="Intro", params={})], selection)


# --- whole-track structures ------------------------------------------------


def test_every_structure_lays_out_a_playable_arrangement(project, selection):
    for name in moves.STRUCTURES:
        after = apply_actions(project, [Action(kind="move", params={"name": "structure", "structure": name})], selection)
        added = after.sections[len(project.sections):]
        assert len(added) == len(moves.STRUCTURES[name][1])
        assert all(1 <= s.bars <= 64 and 0 <= s.energy <= 1 for s in added)


def test_a_structure_never_deletes_what_is_already_there(project, selection):
    after = apply_actions(project, [Action(kind="move", params={"name": "structure", "structure": "club"})], selection)
    assert [s.name for s in after.sections][: len(project.sections)] == [s.name for s in project.sections]
    for track in after.tracks:
        before = next(t for t in project.tracks if t.id == track.id)
        assert all(any(c.section_id == old.section_id for c in track.clips) for old in before.clips)


def test_a_drop_is_written_at_full_energy_and_a_breakdown_is_not(project, selection):
    after = apply_actions(project, [Action(kind="move", params={"name": "structure", "structure": "club"})], selection)
    by_name = {s.name: s for s in after.sections}
    assert by_name["Drop"].energy == 1.0
    assert by_name["Breakdown"].energy < 0.4


def test_section_names_never_collide_with_the_ones_already_there(project, selection):
    after = apply_actions(project, [Action(kind="move", params={"name": "structure", "structure": "club"})], selection)
    names = [s.name for s in after.sections]
    assert len(names) == len(set(names))


def test_an_unknown_structure_is_refused_by_name(project, selection):
    with pytest.raises(EditError, match="club"):
        apply_actions(project, [Action(kind="move", params={"name": "structure", "structure": "jungle"})], selection)


def test_a_structure_that_would_not_fit_is_refused_rather_than_truncated(project, selection):
    long = apply_actions(project, [Action(kind="move", params={"name": "structure", "structure": "anthem"})], selection)
    with pytest.raises(EditError):
        apply_actions(long, [Action(kind="move", params={"name": "structure", "structure": "anthem", "bars": 64})], selection)


# --- modes -----------------------------------------------------------------


def scale_run(project, section_name="Main"):
    """An eight-note run up the scale on the lead, for watching a mode change."""
    section = next(s for s in project.sections if s.name == section_name)
    lead = next(t for t in project.tracks if t.role == "lead")
    lead.clips = [Clip(name="Run", section_id=section.id, notes=[Note(pitch=p, start=float(i), duration=0.9, velocity=90) for i, p in enumerate([69, 71, 72, 74, 76, 77, 79, 81])])]
    return type(project).model_validate(project.model_dump())


def pitches_of(project, role="lead"):
    return [n.pitch for t in project.tracks if t.role == role for c in t.clips for n in c.notes]


def test_dorian_raises_the_sixth_and_changes_nothing_else(project, selection):
    after = apply_actions(scale_run(project), [Action(kind="project", params={"scale": "dorian"})], selection)
    assert pitches_of(after) == [69, 71, 72, 74, 76, 78, 79, 81], "only the F moves, and it moves up one"


def test_phrygian_flattens_the_second_and_changes_nothing_else(project, selection):
    after = apply_actions(scale_run(project), [Action(kind="project", params={"scale": "phrygian"})], selection)
    assert pitches_of(after) == [69, 70, 72, 74, 76, 77, 79, 81], "only the B moves, and it moves down one"


def test_a_melody_keeps_its_shape_through_any_mode_change(project, selection):
    run = scale_run(project)
    for mode in ("major", "dorian", "phrygian", "lydian", "mixolydian"):
        after = apply_actions(run, [Action(kind="project", params={"scale": mode})], selection)
        moved = pitches_of(after)
        assert len(moved) == 8
        assert moved == sorted(moved), f"{mode} should still be a rising run"
        assert moved[-1] - moved[0] == 12, f"{mode} should still span an octave"


def test_every_mode_produces_seven_usable_chords():
    for mode in SCALES:
        chords = harmony.diatonic("A", mode)
        assert len({c.degree for c in chords}) == 7
        assert all(c.quality in harmony.TRIADS for c in chords)


def test_the_borrowed_major_dominant_appears_where_the_fifth_is_minor():
    """The cadence wants it in the modes that do not already have it."""
    for mode in ("minor", "dorian", "mixolydian"):
        symbols = [c.symbol for c in harmony.diatonic("A", mode)]
        assert symbols.count("E") == 1, f"{mode} should borrow a major V"
    assert "E" in [c.symbol for c in harmony.diatonic("A", "major")], "major already has one"


def test_a_progression_that_lands_on_a_diminished_chord_says_so(project, selection):
    findings: list[str] = []
    dorian = apply_actions(project, [Action(kind="project", params={"scale": "dorian"})], selection)
    apply_actions(dorian, [Action(kind="harmony", track="chords", section="Main", params={"progression": "trance"})], selection, findings)
    assert any("diminished" in line and "dorian" in line for line in findings)


def test_composing_in_a_mode_stays_in_that_mode(project, selection):
    for mode in SCALES:
        in_mode = apply_actions(project, [Action(kind="project", params={"scale": mode})], selection)
        written = apply_actions(in_mode, [Action(kind="compose", track="lead", section="Main", params={"density": 0.9})], selection)
        allowed = {(9 + step) % 12 for step in SCALE_STEPS[mode]}
        assert {p % 12 for p in pitches_of(written)} <= allowed, mode


def test_the_scales_offered_in_the_studio_all_exist_in_python():
    source = (ROOT / "src/App.tsx").read_text()
    block = re.search(r"const SCALES = \[(.*?)\];", source, re.S)
    assert block, "src/App.tsx must list the scales it offers"
    assert set(re.findall(r'"(\w+)"', block.group(1))) == set(SCALES)


# --- copying material between sections -------------------------------------


def test_copying_a_section_fills_one_that_already_exists(project, selection):
    after = apply_actions(project, [Action(kind="arrange", section="Outro", params={"operation": "copy", "from_section": "Main"})], selection)
    assert len(after.sections) == len(project.sections), "copy fills a section; duplicate makes one"
    main = next(s for s in after.sections if s.name == "Main")
    outro = next(s for s in after.sections if s.name == "Outro")
    lead = next(t for t in after.tracks if t.role == "lead")
    source = next(c for c in lead.clips if c.section_id == main.id)
    copied = next(c for c in lead.clips if c.section_id == outro.id)
    limit = outro.bars * 4
    assert [(n.pitch, n.start) for n in copied.notes] == [(n.pitch, n.start) for n in source.notes if n.start < limit]


def test_a_copy_never_reuses_a_note_identity(project, selection):
    after = apply_actions(project, [Action(kind="arrange", section="Outro", params={"operation": "copy", "from_section": "Main"})], selection)
    ids = [n.id for t in after.tracks for c in t.clips for n in c.notes]
    assert len(ids) == len(set(ids))


def test_copying_only_the_tracks_that_were_named(project, selection):
    after = apply_actions(project, [Action(kind="arrange", section="Outro", params={"operation": "copy", "from_section": "Main", "tracks": ["bass"]})], selection)
    outro = next(s for s in after.sections if s.name == "Outro")
    before = {t.role: len([c for c in t.clips if c.section_id == outro.id]) for t in project.tracks}
    now = {t.role: len([c for c in t.clips if c.section_id == outro.id]) for t in after.tracks}
    assert now["bass"] == 1
    assert now["lead"] == before["lead"], "the lead was not named, so it was left alone"


def test_automation_travels_with_the_copy_and_stays_in_range(project, selection):
    built = apply_actions(project, [Action(kind="move", section="Main", params={"name": "buildup", "riser": False, "roll": False})], selection)
    after = apply_actions(built, [Action(kind="arrange", section="Outro", params={"operation": "copy", "from_section": "Main"})], selection)
    outro = next(s for s in after.sections if s.name == "Outro")
    lanes = [a for t in after.tracks for a in t.automation if a.section_id == outro.id]
    assert lanes, "a copied section should bring its automation"
    assert all(point[0] <= outro.bars * 4 + 1e-9 for lane in lanes for point in lane.points)


def test_a_section_cannot_be_copied_onto_itself(project, selection):
    with pytest.raises(EditError, match="already itself"):
        apply_actions(project, [Action(kind="arrange", section="Main", params={"operation": "copy", "from_section": "Main"})], selection)


def test_copying_into_a_protected_section_is_refused(project, selection):
    locked = apply_actions(project, [Action(kind="protect", track="drums", params={"locked": True})], selection)
    with pytest.raises(EditError, match="protected"):
        apply_actions(locked, [Action(kind="arrange", section="Main", params={"operation": "copy", "from_section": "Intro"})], selection)


def test_copying_from_an_empty_section_says_so(project, selection):
    empty = apply_actions(project, [Action(kind="arrange", params={"operation": "add", "name": "Empty", "bars": 4})], selection)
    with pytest.raises(EditError, match="nothing in Empty"):
        apply_actions(empty, [Action(kind="arrange", section="Outro", params={"operation": "copy", "from_section": "Empty"})], selection)


def test_every_automatable_parameter_reaches_a_real_signal():
    """A curve on a parameter the audio engine cannot route is a silent no-op."""
    chain = (ROOT / "src/audio/effects.ts").read_text()
    block = re.search(r"export type Chain = \{(.*?)\n\};", chain, re.S)
    assert block, "src/audio/effects.ts must export a Chain type"
    exposed = set(re.findall(r"^\s+(\w+)\??:\s*Automatable", block.group(1), re.M))
    # The mixer owns these two; everything else has to come from the chain.
    assert set(AUTOMATABLE) - {"volume_db", "pan"} == exposed


def test_a_curve_can_be_drawn_on_every_automatable_parameter(project, selection):
    for parameter, (low, high) in AUTOMATION_RANGES.items():
        points = [[0, low], [8, high]]
        after = apply_actions(project, [Action(kind="automation", track="lead", section="Main", params={"parameter": parameter, "points": points})], selection)
        lead = next(t for t in after.tracks if t.role == "lead")
        assert any(a.parameter == parameter for a in lead.automation), parameter


def test_a_curve_outside_a_parameter_range_is_refused_in_plain_language(project, selection):
    with pytest.raises(EditError) as caught:
        apply_actions(project, [Action(kind="automation", track="lead", section="Main", params={"parameter": "drive", "points": [[0, 0], [8, 5]]})], selection)
    assert "between 0 and 0.8" in str(caught.value)
    assert "pydantic" not in str(caught.value) and "validation error" not in str(caught.value).lower()


def test_a_curve_on_something_that_is_not_a_parameter_is_refused_by_name(project, selection):
    with pytest.raises(Unsupported, match="cutoff"):
        apply_actions(project, [Action(kind="automation", track="lead", section="Main", params={"parameter": "tempo", "points": [[0, 100], [8, 128]]})], selection)


def javascript_names(source: str, name: str) -> list[str]:
    """The names out of one exported TypeScript array, whether it holds bare
    strings or [name, description] pairs."""
    block = re.search(rf"export const {name}[^=]*=\s*\[(.*?)\n\]\s*as const;", source, re.S)
    assert block, f"src/Write.tsx must export {name}"
    body = block.group(1)
    pairs = re.findall(r'\[\s*"([^"]*)"\s*,', body)
    return pairs if pairs else re.findall(r'"([^"]*)"', body)


def test_the_studio_offers_exactly_the_musical_vocabulary_python_has():
    """A control offering a melody shape the engine has never heard of is a
    button that reports success and changes nothing — the failure this project
    exists to make impossible. So the two lists are compared, not trusted.

    This caught a progression called "emotional" in the UI that Python has never
    had."""
    from rdx.musical import bass as bass_module
    from rdx.musical import drums as drums_module
    from rdx.musical import genres as genres_module
    from rdx.musical import harmony as harmony_module
    from rdx.musical import motif as motif_module

    source = (ROOT / "src/Write.tsx").read_text()
    for name, expected in (
        ("CELLS", set(motif_module.CELLS)),
        ("SHAPES", set(motif_module.SHAPES)),
        ("FORMS", set(motif_module.FORMS)),
        ("BASS_PATTERNS", set(bass_module.PATTERNS)),
        ("KITS", set(drums_module.KITS)),
        ("GENRES", set(genres_module.GENRES)),
        ("PROGRESSIONS", set(harmony_module.NAMED_PROGRESSIONS)),
    ):
        assert set(javascript_names(source, name)) == expected, name
