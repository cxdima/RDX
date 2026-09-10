"""Ducking: the pump that holds electronic music together.

A kick and a pad fighting for the same moment is the oldest problem in dance
music, and the answer producers reached for is to pull everything else down
each time the kick lands. The result is not really a mix decision — it is the
groove. "Sidechain the pads to the kick" is a rhythmic instruction.

RDX does this the way a producer with a volume shaper does it, not the way a
compressor does it: the *source track's notes* generate the ducking curve, so
the shape is knowable before a single sample is rendered. That has three
consequences worth the choice.

- It is inspectable. `ducking_points` returns the exact curve, so a test can
  assert that the pad is 12 dB down when the kick hits and back up by the next
  one. A real detector could only be listened to.
- It is identical in playback and in export. `src/audio/sidechain.ts` mirrors
  this file and `tests/test_musical.py` asserts the two tables stay the same.
- It never chases the wrong thing. A compressor keyed off a drum bus ducks on
  the hats too unless you filter it; here the trigger voice is named.

Depth is a linear gain floor, because that is what the ear hears and what the
gain node takes: `amount` 0.75 leaves a quarter of the level, which is 12 dB
of ducking. `depth_db` converts for anything the user reads.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from ..domain import Note

# Drum voices that can key a duck, by the name a producer would say.
TRIGGERS = {"kick": 36, "snare": 38, "clap": 39, "rim": 37, "hat": 42, "all": None}

CURVES = ("exponential", "linear", "smooth")


@dataclass(frozen=True)
class Shape:
    """One named ducking feel and the settings behind it."""

    meaning: str
    amount: float
    release: float  # beats for the level to come back
    attack: float = 0.02  # beats to fall; ~10 ms at 128 BPM
    curve: str = "exponential"


# The shapes worth naming. Release is in beats, so they follow the tempo:
# a "pump" is one beat of recovery whether the track runs at 124 or 140.
SHAPES: dict[str, Shape] = {
    "pump": Shape("the classic quarter-note pump, most of the level gone under each kick", amount=0.75, release=0.95, curve="exponential"),
    "tight": Shape("a short duck that gets out of the kick's way and no more", amount=0.55, release=0.35, attack=0.008),
    "gentle": Shape("just enough to stop the two parts colliding", amount=0.3, release=0.6),
    "breathing": Shape("a long swell back in, felt more than heard", amount=0.65, release=1.9, curve="smooth"),
    "extreme": Shape("almost silent under every hit, the effect as the point", amount=0.93, release=1.1, curve="smooth"),
    "eighth": Shape("a fast pump that recovers within an eighth note", amount=0.7, release=0.48, attack=0.006),
}


def rounded(value: float, places: int) -> float:
    """Round half away from zero, the way JavaScript's Math.round does.

    Python rounds halves to even, so 0.85125 becomes 0.8512 here and 0.8513 in
    the browser. The difference is a ten-thousandth of a beat and inaudible,
    but a mirror that is allowed to drift is the thing this design exists to
    prevent — so both sides round the same way and the curves stay identical.
    """
    factor = 10**places
    return math.floor(value * factor + 0.5) / factor


def depth_db(amount: float) -> float:
    """How far the level falls, in decibels, for an amount from 0 to 1."""
    return round(20 * math.log10(max(1 - amount, 1e-4)), 1)


def recover(progress: float, floor: float, curve: str) -> float:
    """Gain part-way through the recovery, from the floor back to unity.

    exponential is what a compressor releasing actually does — most of the
    level returns early and the last of it creeps back. smooth is the S-curve
    of a volume shaper, which sags longer and is the harder pump. linear is
    the straight line, for when neither should colour it.
    """
    if progress <= 0:
        return floor
    if progress >= 1:
        return 1.0
    span = 1.0 - floor
    if curve == "linear":
        return floor + span * progress
    if curve == "smooth":
        return floor + span * (1 - math.cos(math.pi * progress)) / 2
    if curve == "exponential":
        decay = math.exp(-4 * progress)
        return floor + span * (1 - decay) / (1 - math.exp(-4))
    raise KeyError(curve)


def trigger_beats(notes: list[Note], trigger: str) -> list[float]:
    """The moments a duck fires, from the notes of the source part.

    Hits closer together than a thirty-second are one event: a flammed clap
    should duck once, not twice.
    """
    if trigger not in TRIGGERS:
        raise KeyError(trigger)
    pitch = TRIGGERS[trigger]
    beats = sorted(n.start for n in notes if pitch is None or n.pitch == pitch)
    unique: list[float] = []
    for beat in beats:
        if not unique or beat - unique[-1] > 0.125:
            unique.append(rounded(beat, 4))
    return unique


def ducking_points(triggers: list[float], length: float, *, amount: float, attack: float, release: float, curve: str, steps: int = 8) -> list[list[float]]:
    """The gain curve for one section, as [beat, gain] pairs.

    Gain is linear and multiplies the track's own level, so this composes with
    a volume automation lane rather than fighting it. A trigger arriving during
    a recovery cuts it short, which is exactly what a fast pattern should do.
    """
    if not 0 <= amount <= 1 or attack < 0 or release <= 0 or length <= 0:
        raise ValueError("Ducking settings are outside their ranges")
    floor = rounded(1 - amount, 6)
    points: list[list[float]] = []

    def add(beat: float, gain: float):
        beat = rounded(min(max(beat, 0.0), length), 4)
        gain = rounded(min(max(gain, 0.0), 1.0), 5)
        if points and abs(points[-1][0] - beat) < 1e-6:
            points[-1][1] = gain
        else:
            points.append([beat, gain])

    inside = [t for t in triggers if -attack <= t < length]
    if not inside:
        return [[0.0, 1.0], [rounded(length, 4), 1.0]]
    if inside[0] > 1e-6:
        add(0.0, 1.0)
    for index, beat in enumerate(inside):
        following = inside[index + 1] if index + 1 < len(inside) else length + attack
        add(beat, 1.0 if index == 0 or beat - inside[index - 1] > attack + 1e-9 else floor)
        landing = min(beat + attack, following)
        add(landing, floor)
        for step in range(1, steps + 1):
            moment = landing + release * step / steps
            if moment >= following - 1e-9 or moment > length:
                break
            add(moment, recover(step / steps, floor, curve))
        if landing + release < following - 1e-9 and landing + release <= length:
            add(landing + release, 1.0)
    if points[-1][0] < length - 1e-6:
        add(length, points[-1][1] if points[-1][1] >= 1.0 else 1.0)
    return points


def describe_settings(amount: float, release: float, curve: str, trigger: str) -> str:
    """A plain reading of a ducking setting, for the summary the user reads."""
    beats = "a beat" if abs(release - 1) < 0.12 else f"{round(release, 2)} beats"
    return f"{abs(depth_db(amount))} dB under each {trigger}, back up over {beats} ({curve})"


def nearest_shape(amount: float, release: float, curve: str) -> str | None:
    """The named shape a setting corresponds to, if it is one of them."""
    for name, shape in SHAPES.items():
        if abs(shape.amount - amount) < 1e-6 and abs(shape.release - release) < 1e-6 and shape.curve == curve:
            return name
    return None
