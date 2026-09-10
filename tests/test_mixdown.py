"""Tests for mix judgement.

These assert that a measurement of known audio produces the finding a producer
would give it. The signals are synthesised, so what goes in is exactly known:
if RDX calls a mix muddy, this file says which frequencies made it say so.
"""
from __future__ import annotations

import numpy as np
import pytest
from scipy import signal as sp

from rdx.domain import Action
from rdx.engine import EditError, Unsupported, apply_actions, context, starter_project
from rdx.musical import mixdown

RATE = 44100
SECONDS = 2.0


@pytest.fixture
def project():
    return starter_project()


@pytest.fixture
def names(project):
    return {t.id: (t.name, t.role) for t in project.tracks}


@pytest.fixture
def ids(project):
    return {t.role: t.id for t in project.tracks}


def band_noise(low: float, high: float, amplitude: float, seed: int = 3) -> np.ndarray:
    """Noise confined to one region of the spectrum, at a known level.

    Second-order sections rather than a transfer function: a narrow band at
    44.1 kHz is numerically unstable in the latter and comes out as NaN.
    """
    rng = np.random.default_rng(seed)
    raw = rng.standard_normal(int(RATE * SECONDS))
    sections = sp.butter(6, [low / (RATE / 2), min(high, RATE / 2 - 100) / (RATE / 2)], btype="band", output="sos")
    filtered = sp.sosfilt(sections, raw)
    filtered = filtered / (np.max(np.abs(filtered)) + 1e-12) * amplitude
    return np.repeat(filtered[:, None], 2, axis=1).astype(np.float32)


def pulses(frequency: float, per_second: float, amplitude: float) -> np.ndarray:
    """Short bursts, the way a kick or a clap actually behaves in time."""
    t = np.arange(int(RATE * SECONDS)) / RATE
    envelope = np.zeros_like(t)
    for hit in np.arange(0, SECONDS, 1 / per_second):
        start = int(hit * RATE)
        length = int(0.12 * RATE)
        envelope[start : start + length] = np.exp(-np.linspace(0, 8, length))[: len(envelope) - start]
    tone = np.sin(2 * np.pi * frequency * t) * envelope * amplitude
    return np.repeat(tone[:, None], 2, axis=1).astype(np.float32)


# --- measurement -----------------------------------------------------------


def test_band_energy_finds_the_frequencies_that_are_actually_there():
    energies, total = mixdown.band_energy(band_noise(250, 380, 0.4), RATE)
    shares = mixdown.shares(energies, total)
    assert shares["mud"] > 0.8, "noise between 250 and 380 Hz belongs to the low mids"
    assert shares["air"] < 0.01


def test_a_mono_signal_reads_as_mono_and_a_split_one_does_not():
    mono = band_noise(400, 2000, 0.3)
    assert mixdown.correlation(mono) > 0.99
    wide = mono.copy()
    wide[:, 1] = band_noise(400, 2000, 0.3, seed=99)[:, 0]
    assert mixdown.correlation(wide) < 0.3


def test_loudness_follows_level_the_way_lufs_should():
    quiet = band_noise(100, 5000, 0.05)
    loud = band_noise(100, 5000, 0.5)
    # Ten times the amplitude is 20 dB, and LUFS is a decibel scale.
    assert mixdown.loudness(loud, RATE) - mixdown.loudness(quiet, RATE) == pytest.approx(20, abs=1.5)


def test_silence_reads_as_silence_rather_than_crashing():
    silent = np.zeros((RATE, 2), dtype=np.float32)
    assert mixdown.loudness(silent, RATE) == -70.0
    energies, total = mixdown.band_energy(silent, RATE)
    assert total == 0.0


def test_a_sustained_tone_has_less_dynamic_range_than_pulses(names, ids):
    """A held note is flat; four kicks a second are not. Crest factor sees it."""
    t = np.arange(int(RATE * SECONDS)) / RATE
    held = np.repeat((0.4 * np.sin(2 * np.pi * 80 * t))[:, None], 2, axis=1).astype(np.float32)
    steady = mixdown.analyse({ids["bass"]: held}, RATE, names)
    hits = mixdown.analyse({ids["drums"]: pulses(60, 4, 0.4)}, RATE, names)
    assert steady.crest_db == pytest.approx(3.0, abs=0.5), "a sine peaks 3 dB over its average"
    assert hits.crest_db > steady.crest_db + 8


# --- findings --------------------------------------------------------------


def problems(mix, project) -> set[str]:
    return {f.problem for f in mixdown.findings(mix, project)}


def test_a_pile_up_in_the_low_mids_is_called_muddy(project, names, ids):
    stems = {
        ids["drums"]: pulses(60, 4, 0.3),
        ids["bass"]: band_noise(50, 180, 0.25),
        ids["chords"]: band_noise(210, 390, 0.45),
        ids["lead"]: band_noise(230, 400, 0.45, seed=11),
    }
    mix = mixdown.analyse(stems, RATE, names)
    assert mix.bands["mud"] > mixdown.LIMITS["mud_share"]
    assert "muddy" in problems(mix, project)


def test_a_clean_spread_across_the_spectrum_is_not_called_muddy(project, names, ids):
    stems = {
        ids["drums"]: pulses(60, 4, 0.3),
        ids["bass"]: band_noise(45, 190, 0.3),
        ids["chords"]: band_noise(500, 2200, 0.22),
        ids["lead"]: band_noise(1200, 6000, 0.2),
    }
    mix = mixdown.analyse(stems, RATE, names)
    assert "muddy" not in problems(mix, project)


def test_a_kick_and_a_bass_in_the_same_place_are_told_to_duck(project, names, ids):
    stems = {
        ids["drums"]: pulses(55, 4, 0.4),
        ids["bass"]: band_noise(45, 90, 0.4),
        ids["chords"]: band_noise(600, 2400, 0.2),
    }
    mix = mixdown.analyse(stems, RATE, names)
    masking = [f for f in mixdown.findings(mix, project) if f.problem == "masking"]
    assert masking, "two parts sharing the bottom should be reported"
    ducking = [a for f in masking for a in f.actions if a["kind"] == "sidechain"]
    assert ducking, "the answer to a kick and bass collision is ducking, not an EQ cut"
    assert ducking[0]["track"] == ids["bass"] and ducking[0]["params"]["source"] == ids["drums"]


def test_two_parts_overlapping_in_an_empty_band_is_not_a_collision(project, names, ids):
    """Both tracks have almost no top end, so sharing it evenly means nothing."""
    stems = {ids["bass"]: band_noise(40, 160, 0.4), ids["chords"]: band_noise(45, 170, 0.4, seed=5)}
    mix = mixdown.analyse(stems, RATE, names)
    assert not [c for c in mix.collisions if c.band == "air"]


def test_a_part_far_below_the_others_is_reported_as_buried(project, names, ids):
    stems = {ids["bass"]: band_noise(50, 200, 0.5), ids["lead"]: band_noise(800, 4000, 0.004)}
    found = [f for f in mixdown.findings(mixdown.analyse(stems, RATE, names), project) if f.problem == "buried"]
    assert found and found[0].tracks == [ids["lead"]]
    assert found[0].actions[0]["params"]["delta_db"] > 0


def test_every_finding_states_the_number_that_produced_it(project, names, ids):
    stems = {ids["chords"]: band_noise(210, 390, 0.5), ids["lead"]: band_noise(2600, 7000, 0.5)}
    for finding in mixdown.findings(mixdown.analyse(stems, RATE, names), project):
        assert any(character.isdigit() for character in finding.detail), finding.problem


def test_no_more_than_three_collisions_are_reported(project, names, ids):
    stems = {track_id: band_noise(300, 1800, 0.4, seed=index) for index, track_id in enumerate(ids.values())}
    found = mixdown.findings(mixdown.analyse(stems, RATE, names), project)
    assert len([f for f in found if f.problem == "masking"]) <= 3


# --- the fixes must be real edits ------------------------------------------


def test_every_proposed_fix_is_an_edit_the_engine_will_accept(project, names, ids):
    stems = {
        ids["drums"]: pulses(55, 4, 0.4),
        ids["bass"]: band_noise(45, 100, 0.4),
        ids["chords"]: band_noise(210, 390, 0.5),
        ids["lead"]: band_noise(2600, 7500, 0.5),
    }
    mix = mixdown.analyse(stems, RATE, names)
    found = mixdown.findings(mix, project)
    assert found, "this mix has problems worth naming"
    for finding in found:
        actions = [Action.model_validate(a) for a in finding.actions]
        apply_actions(project, actions)


def test_a_fix_moves_from_the_current_setting_rather_than_from_flat(project, names, ids):
    stems = {ids["chords"]: band_noise(210, 390, 0.5), ids["lead"]: band_noise(215, 395, 0.5, seed=8)}
    mix = mixdown.analyse(stems, RATE, names)
    already = apply_actions(project, [Action(kind="sound", track=ids["chords"], params={"low": -6})])
    cuts = [a for f in mixdown.findings(mix, already) if f.problem == "muddy" for a in f.actions if a["track"] == ids["chords"]]
    assert cuts and cuts[0]["params"]["low"] < -6, "a second pass must not undo the first"


def test_correcting_a_measured_mix_actually_changes_the_project(project, names, ids):
    stems = {ids["chords"]: band_noise(210, 390, 0.5), ids["lead"]: band_noise(215, 395, 0.5, seed=8)}
    measured = mixdown.analyse(stems, RATE, names).as_dict()
    after = apply_actions(project, [Action(kind="mix_fix", params={"problem": "muddy"})], None, None, measured)
    assert after.model_dump() != project.model_dump()


def test_rdx_refuses_to_fix_a_mix_it_has_not_measured(project):
    with pytest.raises(EditError, match="not guess"):
        apply_actions(project, [Action(kind="mix_fix", params={"problem": "muddy"})])


def test_a_problem_the_measurement_does_not_show_is_refused_by_name(project, names, ids):
    stems = {ids["bass"]: band_noise(50, 190, 0.3), ids["chords"]: band_noise(600, 2400, 0.2)}
    measured = mixdown.analyse(stems, RATE, names).as_dict()
    with pytest.raises(Unsupported, match="does not measure"):
        apply_actions(project, [Action(kind="mix_fix", params={"problem": "harsh"})], None, None, measured)


def test_a_measurement_survives_being_stored_and_read_back(names, ids):
    stems = {ids["chords"]: band_noise(210, 390, 0.4), ids["bass"]: band_noise(50, 180, 0.4)}
    original = mixdown.analyse(stems, RATE, names)
    restored = mixdown.Mix.from_dict(original.as_dict())
    assert restored.as_dict() == original.as_dict()


def test_the_model_is_told_which_problems_were_measured_but_not_the_numbers(project, names, ids):
    stems = {ids["chords"]: band_noise(210, 390, 0.5), ids["lead"]: band_noise(215, 395, 0.5, seed=8)}
    measured = mixdown.analyse(stems, RATE, names).as_dict()
    ctx = context(project, ids["lead"], project.sections[0].id, measured)
    assert "muddy" in ctx["selected"]["mix_measured"]
    assert "LUFS" not in repr(ctx)


def test_the_summary_reads_as_sentences_not_as_numbers(project, names, ids):
    stems = {ids["chords"]: band_noise(210, 390, 0.5), ids["bass"]: band_noise(50, 180, 0.3)}
    mix = mixdown.analyse(stems, RATE, names)
    text = mixdown.summarise(mix, mixdown.findings(mix, project))
    assert "LUFS" in text and "dynamic range" in text
    assert "The mix is muddy" in text
