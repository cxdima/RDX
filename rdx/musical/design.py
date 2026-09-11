"""Sound design: the patches a producer asks for by name.

`character.py` answers *"make it warmer"* — a nudge to a sound that already
exists. This file answers *"give me a reese bass"*, which is a different kind of
request: not an adjustment but a whole patch, twelve parameters at once, with a
name that means something specific to everyone who has made this music.

Each entry is the complete recipe. That is the point: a producer can read what
RDX thinks a hoover is, disagree, and change the line. A model asked to invent
twelve synth parameters for "hoover" would produce twelve plausible numbers and
no way to tell whether they were right.

Every patch here is buildable from RDX's own synth — oscillator, unison, sub,
filter with an envelope, drive, crush, an LFO with a destination, and the space
section. Nothing names a sound the engine cannot actually make.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..domain import Sound


@dataclass(frozen=True)
class Patch:
    """One named sound and every parameter that makes it that sound."""

    meaning: str
    roles: tuple[str, ...]  # where it belongs, so RDX can say when it does not
    settings: dict[str, float | int | str] = field(default_factory=dict)


PATCHES: dict[str, Patch] = {
    "reese": Patch(
        "two detuned saws beating against each other, filtered low and wide — the drum and bass staple",
        ("bass",),
        {"preset": "saw", "wave": "saw", "unison": 4, "spread": 28, "sub": 0.4, "cutoff": 700, "resonance": 3.5,
         "attack": 0.01, "decay": 0.4, "sustain": 0.9, "release": 0.25, "drive": 0.2, "width": 0.35, "low": 3, "reverb": 0, "delay": 0},
    ),
    "acid": Patch(
        "a resonant filter envelope on every note, the 303 sound",
        ("bass", "lead"),
        {"preset": "saw", "wave": "saw", "unison": 1, "cutoff": 320, "resonance": 11, "filter_env": 0.85, "filter_decay": 0.22,
         "attack": 0.003, "decay": 0.12, "sustain": 0.15, "release": 0.1, "drive": 0.35, "glide": 0.06, "reverb": 0.08},
    ),
    "supersaw_lead": Patch(
        "seven detuned saws, wide and bright — the trance lead",
        ("lead", "chords"),
        {"preset": "supersaw", "unison": 7, "spread": 45, "cutoff": 13000, "resonance": 1.2,
         "attack": 0.02, "decay": 0.35, "sustain": 0.75, "release": 0.55, "chorus": 0.3, "width": 0.65, "reverb": 0.28, "delay": 0.12},
    ),
    "hoover": Patch(
        "the rave hoover: detuned saws, a sweeping filter and heavy drive",
        ("lead",),
        {"preset": "saw", "wave": "saw", "unison": 6, "spread": 70, "cutoff": 900, "resonance": 6, "filter_env": 0.7, "filter_decay": 0.9,
         "attack": 0.02, "decay": 0.6, "sustain": 0.7, "release": 0.4, "drive": 0.45, "chorus": 0.35, "width": 0.5, "glide": 0.08},
    ),
    "pluck_stab": Patch(
        "short, bright and gone before the next one — the offbeat stab",
        ("lead", "chords"),
        {"preset": "pluck", "wave": "saw", "unison": 2, "spread": 14, "cutoff": 5200, "resonance": 2.5, "filter_env": 0.6, "filter_decay": 0.14,
         "attack": 0.002, "decay": 0.14, "sustain": 0.0, "release": 0.14, "reverb": 0.2, "delay": 0.18, "width": 0.3},
    ),
    "sub_bass": Patch(
        "a pure sine under everything, with nothing above it to get in the way",
        ("bass",),
        {"preset": "sub", "wave": "sine", "unison": 1, "cutoff": 220, "resonance": 0.7,
         "attack": 0.006, "decay": 0.2, "sustain": 0.95, "release": 0.18, "sub": 0.0, "width": 0, "reverb": 0, "delay": 0, "low": 2},
    ),
    "donk": Patch(
        "a hard, hollow square with a fast filter snap",
        ("lead", "bass"),
        {"preset": "saw", "wave": "square", "unison": 1, "cutoff": 1400, "resonance": 8, "filter_env": 0.75, "filter_decay": 0.1,
         "attack": 0.001, "decay": 0.09, "sustain": 0.0, "release": 0.09, "drive": 0.3, "high": 2},
    ),
    "wobble": Patch(
        "a low saw with the filter swinging under an LFO",
        ("bass",),
        {"preset": "saw", "wave": "saw", "unison": 2, "spread": 16, "sub": 0.45, "cutoff": 500, "resonance": 7,
         "attack": 0.01, "decay": 0.3, "sustain": 0.95, "release": 0.2, "drive": 0.3, "lfo_target": "cutoff", "lfo_depth": 0.85, "lfo_rate": 5.5},
    ),
    "warm_pad": Patch(
        "slow, thick and far back, with nothing sharp in it",
        ("pad", "chords"),
        {"preset": "pad", "unison": 3, "spread": 26, "cutoff": 2600, "resonance": 0.8,
         "attack": 1.2, "decay": 0.6, "sustain": 0.9, "release": 2.6, "chorus": 0.4, "width": 0.6, "reverb": 0.5, "high": -3, "low": 2},
    ),
    "glass_pad": Patch(
        "high, still and clean, sitting above the arrangement rather than under it",
        ("pad", "chords"),
        {"preset": "choir", "unison": 5, "spread": 50, "cutoff": 9000, "resonance": 1,
         "attack": 0.9, "decay": 0.5, "sustain": 0.85, "release": 2.8, "chorus": 0.35, "width": 0.7, "reverb": 0.55, "high": 3, "low": -4},
    ),
    "bell_lead": Patch(
        "an FM bell with a long ring and a lot of air around it",
        ("lead",),
        {"preset": "bell", "cutoff": 15000, "resonance": 0.8,
         "attack": 0.002, "decay": 0.9, "sustain": 0.0, "release": 1.8, "reverb": 0.45, "delay": 0.22, "width": 0.4, "high": 2},
    ),
    "organ": Patch(
        "flat and held, no attack shape at all — an organ is its sustain",
        ("chords", "pad"),
        {"preset": "sine", "wave": "square", "unison": 3, "spread": 8, "sub": 0.5, "cutoff": 4000, "resonance": 0.7,
         "attack": 0.004, "decay": 0.05, "sustain": 1.0, "release": 0.12, "reverb": 0.2, "width": 0.25},
    ),
    "gritty_bass": Patch(
        "driven and bit-crushed, more texture than tone",
        ("bass",),
        {"preset": "saw", "wave": "square", "unison": 2, "spread": 10, "sub": 0.35, "cutoff": 900, "resonance": 4,
         "attack": 0.004, "decay": 0.25, "sustain": 0.8, "release": 0.15, "drive": 0.55, "crush": 0.4, "mid": 2},
    ),
    "vibrato_lead": Patch(
        "a singing lead with pitch movement on every held note",
        ("lead",),
        {"preset": "saw", "wave": "triangle", "unison": 2, "spread": 12, "cutoff": 7000, "resonance": 1.5,
         "attack": 0.05, "decay": 0.3, "sustain": 0.85, "release": 0.4, "lfo_target": "pitch", "lfo_depth": 0.35, "lfo_rate": 5.5, "reverb": 0.25},
    ),
    "tremolo_keys": Patch(
        "a held chord pulsing in and out under an LFO",
        ("chords", "pad"),
        {"preset": "sine", "wave": "triangle", "unison": 2, "spread": 10, "cutoff": 3500, "resonance": 0.8,
         "attack": 0.02, "decay": 0.3, "sustain": 0.9, "release": 0.6, "lfo_target": "volume", "lfo_depth": 0.7, "lfo_rate": 6, "reverb": 0.3},
    ),
    "riser_noise": Patch(
        "filtered noise that only becomes anything when a filter sweeps it",
        ("pad", "lead"),
        {"preset": "noise", "cutoff": 1200, "resonance": 2.5, "attack": 0.6, "decay": 0.2, "sustain": 1.0, "release": 1.2, "reverb": 0.35, "width": 0.5},
    ),
}


def patch_settings(name: str) -> dict:
    """The full parameter set for a named patch, validated against the model."""
    if name not in PATCHES:
        raise KeyError(name)
    settings = dict(PATCHES[name].settings)
    Sound.model_validate({**Sound().model_dump(), **settings})
    return settings


def suits(name: str, role: str) -> bool:
    """Whether a patch belongs on a track of this role."""
    return role in PATCHES[name].roles


def describe_patch(name: str) -> str:
    return f"{name.replace('_', ' ')}: {PATCHES[name].meaning}"
