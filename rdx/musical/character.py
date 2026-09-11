"""Musical adjectives mapped to concrete sound changes.

A producer says "warm it up", not "cutoff 2400, high -3 dB". This table is
that translation, and it is the reason RDX can be checked: every entry is a
claim about what a word means, visible and arguable, not buried in weights.

Changes blend with an intensity from 0 to 1 so "a little warmer" and "much
warmer" are the same word at different strengths.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..domain import Sound

# Field bounds come from the Sound model itself so they can never drift. Only
# the numeric fields are here: a blend is a number moving, and "60% of the way
# to a square wave" is not a sound.
BOUNDS = {
    name: (
        next((m.ge for m in info.metadata if hasattr(m, "ge")), None),
        next((m.le for m in info.metadata if hasattr(m, "le")), None),
    )
    for name, info in Sound.model_fields.items()
    if info.annotation in (float, int)
}


@dataclass(frozen=True)
class Character:
    """One musical adjective and the sound change it stands for."""

    meaning: str
    scale: dict[str, float] = field(default_factory=dict)  # multiply
    shift: dict[str, float] = field(default_factory=dict)  # add
    toward: dict[str, float] = field(default_factory=dict)  # move toward a value
    # Choices rather than amounts — which LFO destination, which waveform.
    # These are set outright; the intensity lands on the depth beside them.
    select: dict[str, str] = field(default_factory=dict)
    opposite: str | None = None


CHARACTERS: dict[str, Character] = {
    "warm": Character(
        "rolls off the top end and fills in the body",
        scale={"cutoff": 0.6}, shift={"high": -3, "low": 1.5, "drive": 0.05}, opposite="bright",
    ),
    "bright": Character(
        "opens the filter and lifts the top end",
        scale={"cutoff": 1.8}, shift={"high": 3, "mid": 1}, opposite="warm",
    ),
    "dark": Character(
        "closes the filter well down and cuts the highs",
        scale={"cutoff": 0.45}, shift={"high": -5}, opposite="bright",
    ),
    "soft": Character(
        "eases the attack, removes grit and takes the edge off",
        shift={"attack": 0.08, "release": 0.3, "high": -2}, toward={"drive": 0}, opposite="hard",
    ),
    "hard": Character(
        "instant attack with drive and a resonant edge",
        toward={"attack": 0.002}, shift={"drive": 0.2, "resonance": 2, "high": 2}, opposite="soft",
    ),
    "punchy": Character(
        "instant attack, short tail and a lift in the mids",
        toward={"attack": 0.002}, scale={"release": 0.5}, shift={"drive": 0.08, "mid": 2},
    ),
    "thin": Character(
        "takes weight out of the bottom",
        shift={"low": -6, "mid": -1}, opposite="fat",
    ),
    "fat": Character(
        "adds low weight, chorus thickness and stereo size",
        shift={"low": 4, "chorus": 0.25, "width": 0.3, "drive": 0.05}, opposite="thin",
    ),
    "wide": Character(
        "spreads the sound across the stereo field",
        shift={"width": 0.5, "chorus": 0.3, "autopan": 0.15}, opposite="narrow",
    ),
    "narrow": Character(
        "pulls the sound back to the centre",
        toward={"width": 0, "chorus": 0, "autopan": 0}, opposite="wide",
    ),
    "dry": Character(
        "removes the reverb and echo",
        toward={"reverb": 0, "delay": 0}, opposite="wet",
    ),
    "wet": Character(
        "adds reverb and echo around the sound",
        shift={"reverb": 0.3, "delay": 0.1}, opposite="dry",
    ),
    "dreamy": Character(
        "slow attack, long tail, chorus and a lot of space",
        shift={"reverb": 0.35, "attack": 0.3, "release": 1.0, "chorus": 0.3}, scale={"cutoff": 0.8},
    ),
    "lush": Character(
        "thick chorus, stereo width and a bed of reverb",
        shift={"chorus": 0.35, "width": 0.4, "reverb": 0.2, "low": 1},
    ),
    "gritty": Character(
        "drives the signal and pushes the mids forward",
        shift={"drive": 0.25, "mid": 2}, opposite="clean",
    ),
    "clean": Character(
        "removes drive and resonance",
        toward={"drive": 0, "resonance": 1}, opposite="gritty",
    ),
    "sharp": Character(
        "instant attack with a resonant, cutting top",
        toward={"attack": 0.002}, shift={"resonance": 2, "high": 3}, opposite="smooth",
    ),
    "smooth": Character(
        "eases resonance and the top end, softens the attack",
        toward={"resonance": 0.7}, shift={"high": -2, "attack": 0.03}, opposite="sharp",
    ),
    "huge": Character(
        "stereo size, long tail, chorus and low weight",
        shift={"width": 0.5, "reverb": 0.25, "chorus": 0.3, "low": 3, "release": 0.8},
    ),
    "tight": Character(
        "short tail, quick attack and much less space",
        scale={"release": 0.4, "reverb": 0.4}, toward={"attack": 0.003}, opposite="loose",
    ),
    "loose": Character(
        "longer tail and a slower attack",
        scale={"release": 2.0}, shift={"attack": 0.05}, opposite="tight",
    ),
    "airy": Character(
        "lifts the very top and adds a little space",
        scale={"cutoff": 1.4}, shift={"high": 4, "reverb": 0.2},
    ),
    "clear": Character(
        "cleans out the low mud and lifts definition",
        shift={"low": -3, "mid": -2, "high": 2},
    ),
    "moving": Character(
        "adds panning and flanger motion",
        shift={"autopan": 0.3, "flanger": 0.2}, toward={"motion_rate": 0.5}, opposite="still",
    ),
    "still": Character(
        "removes all modulation movement",
        toward={"autopan": 0, "flanger": 0, "phaser": 0, "lfo_depth": 0}, select={"lfo_target": "off"}, opposite="moving",
    ),
    "swirling": Character(
        "deep phaser and flanger at a slow rate",
        shift={"phaser": 0.4, "flanger": 0.3}, toward={"motion_rate": 0.25},
    ),
    "metallic": Character(
        "heavy flanger with a resonant, ringing top",
        shift={"flanger": 0.5, "resonance": 3, "high": 3},
    ),
    "goosebumps": Character(
        "the full-body treatment: stereo width, flanger motion, panning and space",
        shift={"width": 0.5, "flanger": 0.35, "autopan": 0.25, "reverb": 0.25, "chorus": 0.2},
        toward={"motion_rate": 0.3},
    ),
    # Words that reach the synth rather than the effects. The envelope and the
    # filter envelope are what separate one instrument from another, so these
    # are the adjectives a sound designer actually reaches for.
    "plucky": Character(
        "instant attack, fast decay and nothing left holding",
        toward={"attack": 0.003, "sustain": 0.05}, scale={"decay": 0.4, "release": 0.5}, opposite="sustained",
    ),
    "sustained": Character(
        "holds at full level for as long as the note lasts",
        toward={"sustain": 1.0}, shift={"decay": 0.2}, opposite="plucky",
    ),
    "acidic": Character(
        "a resonant filter envelope snapping shut on every note",
        toward={"filter_env": 0.85, "filter_decay": 0.22}, shift={"resonance": 6, "drive": 0.2}, scale={"cutoff": 0.3},
    ),
    "snappy": Character(
        "a short filter envelope that gives each note a front edge",
        toward={"filter_env": 0.6, "filter_decay": 0.12, "attack": 0.002}, shift={"resonance": 2},
    ),
    "stacked": Character(
        "more detuned voices, thicker and wider",
        toward={"unison": 7}, shift={"spread": 35, "width": 0.3}, opposite="single",
    ),
    "single": Character(
        "one voice, no detuning, right down the middle",
        toward={"unison": 1, "spread": 0, "width": 0}, opposite="stacked",
    ),
    "deep": Character(
        "a sine an octave below, filling in underneath",
        shift={"sub": 0.5, "low": 2}, scale={"cutoff": 0.8},
    ),
    "crushed": Character(
        "bit reduction and drive, more texture than tone",
        shift={"crush": 0.45, "drive": 0.3, "mid": 2}, opposite="clean",
    ),
    "wobbling": Character(
        "the filter swinging up and down under an LFO",
        select={"lfo_target": "cutoff"}, toward={"lfo_depth": 0.8, "lfo_rate": 5.5}, shift={"resonance": 3},
    ),
    "singing": Character(
        "pitch movement on every held note, the way a voice moves",
        select={"lfo_target": "pitch"}, toward={"lfo_depth": 0.35, "lfo_rate": 5.5}, shift={"attack": 0.04},
    ),
    "pulsing": Character(
        "the level opening and closing under an LFO",
        select={"lfo_target": "volume"}, toward={"lfo_depth": 0.7, "lfo_rate": 6},
    ),
}


# Fields the model stores as whole numbers. Blending toward one has to land on
# an integer: there is no such thing as 4.6 unison voices, and the model will
# refuse it rather than round it quietly.
INTEGER_FIELDS = {name for name, info in Sound.model_fields.items() if info.annotation is int}


def clamp(name: str, value: float) -> float | int:
    low, high = BOUNDS[name]
    if low is not None:
        value = max(low, value)
    if high is not None:
        value = min(high, value)
    return int(round(value)) if name in INTEGER_FIELDS else float(round(value, 4))


def character_changes(sound: Sound, name: str, intensity: float = 0.6) -> dict[str, float]:
    """Return the Sound fields a character would change, already clamped.

    Raises KeyError for an unknown word so callers can tell the user plainly
    rather than applying something arbitrary.
    """
    entry = CHARACTERS[name]
    if not 0 < intensity <= 1:
        raise ValueError("Intensity must be greater than zero and at most one")
    current = sound.model_dump()
    changes: dict[str, float | str] = dict(entry.select)
    for target, factor in entry.scale.items():
        changes[target] = clamp(target, current[target] * (1 + (factor - 1) * intensity))
    for target, amount in entry.shift.items():
        base = changes.get(target, current[target])
        changes[target] = clamp(target, base + amount * intensity)
    for target, goal in entry.toward.items():
        base = changes.get(target, current[target])
        changes[target] = clamp(target, base + (goal - base) * intensity)
    return {k: v for k, v in changes.items() if isinstance(v, str) or abs(v - current[k]) > 1e-9}
