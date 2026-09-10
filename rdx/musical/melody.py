"""Shaping a phrase: what a producer means by "more space" or "let it rise".

`transpose` moves notes and `rhythm` moves them onto a grid. Neither one can
answer *"there's too much going on"*, *"the melody should climb at the end"* or
*"it's too repetitive"*, because those are statements about the **shape** of a
phrase rather than about any note in it.

So this module works on contour and density. Everything here takes a list of
notes and returns a new list — no project, no side effects — which is what
makes each claim testable: "thin it out" must remove notes and keep the ones
on the strong beats; "rise at the end" must raise the tail and leave the
opening alone.

Two rules hold throughout, because breaking either turns a shaped phrase into
a different phrase:

- **Nothing leaves the key.** Every pitch change lands on a scale degree, so a
  melody cannot be shaped into a wrong note.
- **Nothing leaves the section.** Notes are never pushed past the end of the
  bar count they were written for.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass

from ..domain import Note

MAJOR = (0, 2, 4, 5, 7, 9, 11)
MINOR = (0, 2, 3, 5, 7, 8, 10)
PITCH_CLASSES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")

SHAPES = ("rise", "fall", "arch", "valley", "flat")


def steps(scale: str) -> tuple[int, ...]:
    return MINOR if scale == "minor" else MAJOR


def scale_pitches(key: str, scale: str, low: int = 0, high: int = 127) -> list[int]:
    """Every playable pitch in the key, ascending."""
    root = PITCH_CLASSES.index(key)
    return [p for p in range(low, high + 1) if (p - root) % 12 in steps(scale)]


def snap(pitch: int, key: str, scale: str, prefer_up: bool = True) -> int:
    """The nearest pitch in the key, so shaping can never invent a wrong note."""
    allowed = scale_pitches(key, scale, max(0, pitch - 12), min(127, pitch + 12))
    if not allowed:
        return pitch
    return min(allowed, key=lambda p: (abs(p - pitch), -(p > pitch) if prefer_up else (p > pitch)))


def strength(note: Note) -> float:
    """How structurally important a note is, so thinning keeps the skeleton.

    Downbeats first, then halves, then the note's own weight. A phrase thinned
    by this rule still reads as the same phrase.
    """
    position = note.start % 4
    metre = 3.0 if position < 1e-6 else 2.0 if abs(position - 2) < 1e-6 else 1.0 if abs(position % 1) < 1e-6 else 0.0
    return metre * 4 + note.duration + note.velocity / 200


def ordered(notes: list[Note]) -> list[Note]:
    return sorted((n.model_copy(deep=True) for n in notes), key=lambda n: (n.start, n.pitch))


def space(notes: list[Note], *, amount: float = 0.4, length: float | None = None) -> list[Note]:
    """Fewer notes, and the survivors held longer — "give it more room".

    Removing notes alone leaves gaps that sound like mistakes. Letting each
    remaining note run up to where the next one starts is what turns a busy
    line into a spacious one.
    """
    if not 0 < amount < 1:
        raise ValueError("Thinning has to remove some of the notes but not all of them")
    phrase = ordered(notes)
    if len(phrase) < 3:
        return phrase
    keep = max(2, round(len(phrase) * (1 - amount)))
    chosen = sorted(sorted(phrase, key=strength, reverse=True)[:keep], key=lambda n: (n.start, n.pitch))
    end = length if length is not None else max(n.start + n.duration for n in phrase)
    for index, note in enumerate(chosen):
        following = next((n.start for n in chosen[index + 1 :] if n.start > note.start + 1e-6), end)
        note.duration = round(max(note.duration, min(following - note.start, note.duration * 2.5)), 4)
    return chosen


def fill(notes: list[Note], *, amount: float = 0.5, key: str = "A", scale: str = "minor", length: float | None = None, seed: int = 0) -> list[Note]:
    """More movement — a passing note between the notes that are already there.

    Added notes sit in the gap and step towards the note that follows, which is
    what makes them sound like part of the line rather than sprinkled on top.
    """
    if not 0 < amount <= 1:
        raise ValueError("Filling has to add some notes")
    phrase = ordered(notes)
    if len(phrase) < 2:
        return phrase
    rng = random.Random(f"fill:{seed}:{amount}")
    end = length if length is not None else max(n.start + n.duration for n in phrase)
    added: list[Note] = []
    for note, following in zip(phrase, phrase[1:] + [None]):
        gap_end = following.start if following else end
        room = gap_end - (note.start + note.duration)
        if room < 0.24 or rng.random() > amount:
            continue
        start = round(note.start + note.duration + room * 0.25, 4)
        duration = round(min(room * 0.6, 0.5), 4)
        target = following.pitch if following else note.pitch
        step = 1 if target > note.pitch else -1 if target < note.pitch else rng.choice((1, -1))
        added.append(Note(pitch=snap(note.pitch + step * 2, key, scale, prefer_up=step > 0), start=start, duration=max(duration, 0.125), velocity=max(1, note.velocity - 14)))
    return sorted(phrase + added, key=lambda n: (n.start, n.pitch))


@dataclass(frozen=True)
class Contour:
    """One phrase shape and how far through the phrase it starts to act."""

    meaning: str
    at: float  # fraction of the phrase where the movement begins


CONTOURS: dict[str, Contour] = {
    "rise": Contour("climbs towards the end", 0.5),
    "fall": Contour("settles downwards towards the end", 0.5),
    "arch": Contour("lifts through the middle and comes back down", 0.0),
    "valley": Contour("dips in the middle and returns", 0.0),
    "flat": Contour("levels the phrase out around its own centre", 0.0),
}


def curve(shape: str, progress: float) -> float:
    """How far the contour has moved at this point, from -1 to 1."""
    if shape == "rise":
        return progress
    if shape == "fall":
        return -progress
    if shape == "arch":
        return math.sin(math.pi * progress)
    if shape == "valley":
        return -math.sin(math.pi * progress)
    if shape == "flat":
        return 0.0
    raise KeyError(shape)


def shape(notes: list[Note], name: str, *, degrees: int = 2, key: str = "A", scale: str = "minor", length: float | None = None) -> list[Note]:
    """Bend a phrase into a shape, moving by scale degrees rather than semitones.

    `degrees` is how far the furthest note travels. Moving in degrees is what
    keeps a shaped melody in the key: two degrees up from the third of a minor
    scale is its fifth, not a note between them.
    """
    if name not in CONTOURS:
        raise KeyError(name)
    if not isinstance(degrees, int) or not 1 <= abs(degrees) <= 7:
        raise ValueError("A phrase can be reshaped by one to seven scale degrees")
    phrase = ordered(notes)
    if not phrase:
        return phrase
    contour = CONTOURS[name]
    start = min(n.start for n in phrase)
    end = length if length is not None else max(n.start + n.duration for n in phrase)
    span = max(end - start, 1e-6)
    ladder = scale_pitches(key, scale)
    if name == "flat":
        centre = sorted(n.pitch for n in phrase)[len(phrase) // 2]
        for note in phrase:
            distance = position_in(ladder, note.pitch) - position_in(ladder, centre)
            note.pitch = step_by(ladder, note.pitch, -round(distance * min(1.0, degrees / 4)))
        return phrase
    for note in phrase:
        progress = (note.start - start) / span
        if progress < contour.at:
            continue
        scaled = (progress - contour.at) / max(1 - contour.at, 1e-6)
        note.pitch = step_by(ladder, note.pitch, round(degrees * curve(name, scaled)))
    return phrase


def position_in(ladder: list[int], pitch: int) -> int:
    """Where a pitch sits on the ladder of the key, nearest rung if it is off it."""
    return min(range(len(ladder)), key=lambda i: abs(ladder[i] - pitch))


def step_by(ladder: list[int], pitch: int, degrees: int) -> int:
    index = position_in(ladder, pitch)
    return ladder[max(0, min(len(ladder) - 1, index + degrees))]


def repetition(notes: list[Note], bars: int) -> float:
    """How much of the phrase is the same bar played again, from 0 to 1.

    Compared as pitch and position within the bar, because a bar repeated at a
    different octave still reads as a repeat.
    """
    if bars < 2 or not notes:
        return 0.0
    signatures = []
    for bar in range(bars):
        inside = [(round(n.start - bar * 4, 3), n.pitch % 12) for n in notes if bar * 4 <= n.start < (bar + 1) * 4]
        signatures.append(tuple(sorted(inside)))
    filled = [s for s in signatures if s]
    if len(filled) < 2:
        return 0.0
    repeats = sum(1 for a, b in zip(filled, filled[1:]) if a == b)
    return repeats / (len(filled) - 1)


def vary(notes: list[Note], bars: int, *, key: str = "A", scale: str = "minor", amount: float = 0.5, seed: int = 0) -> list[Note]:
    """Break up a phrase that repeats itself, leaving the first statement alone.

    The opening bar is what the listener learns; changing it changes the idea.
    Later repeats of it get moved, so the phrase develops instead of looping.
    """
    if not 0 < amount <= 1:
        raise ValueError("Variation has to change something")
    phrase = ordered(notes)
    if bars < 2 or not phrase:
        return phrase
    rng = random.Random(f"vary:{seed}:{amount}")
    ladder = scale_pitches(key, scale)
    signatures: dict[tuple, int] = {}
    for bar in range(bars):
        inside = [n for n in phrase if bar * 4 <= n.start < (bar + 1) * 4]
        if not inside:
            continue
        signature = tuple(sorted((round(n.start - bar * 4, 3), n.pitch % 12) for n in inside))
        first = signatures.setdefault(signature, bar)
        if first == bar:
            continue
        # A repeat of something already heard: move its tail somewhere else.
        movable = sorted(inside, key=lambda n: n.start)[max(1, len(inside) // 2) :]
        for note in movable:
            if rng.random() > amount:
                continue
            note.pitch = step_by(ladder, note.pitch, rng.choice([-2, -1, 1, 2, 3]))
    return phrase
