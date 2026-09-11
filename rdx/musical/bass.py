"""Basslines, which is where a genre actually lives.

RDX's general note generator writes a bass that lands on the kick. That is the
one thing a trance bass never does: it plays in the gaps *between* the kicks,
and that alternation is most of why the music moves. A psytrance bass goes
further — three sixteenths after every kick, never on it, which is the whole
genre in one rhythm.

So the patterns are named and written down here rather than left to a density
parameter. Each one is a claim about a genre that a producer can read and
argue with, and each takes its pitches from the chord progression, so the bass
follows the harmony by construction rather than by coincidence.

Positions are in quarter notes from the start of a bar: 0 is the downbeat and
0.5 is the "and" of one.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..domain import Note


@dataclass(frozen=True)
class Pattern:
    """One bassline rhythm, and what it is for."""

    meaning: str
    hits: tuple[float, ...]  # positions within a bar
    duration: float  # how long each note is held, in beats
    octave_lift: tuple[int, ...] = ()  # which hits jump an octave, by index


PATTERNS: dict[str, Pattern] = {
    "offbeat": Pattern(
        "between every kick — the trance and house bass",
        (0.5, 1.5, 2.5, 3.5), 0.42,
    ),
    "rolling": Pattern(
        "three sixteenths after every kick and never on it — psytrance",
        (0.25, 0.5, 0.75, 1.25, 1.5, 1.75, 2.25, 2.5, 2.75, 3.25, 3.5, 3.75), 0.16,
    ),
    "driving": Pattern(
        "straight eighths, pushing rather than bouncing",
        (0, 0.5, 1, 1.5, 2, 2.5, 3, 3.5), 0.42,
    ),
    "sustained": Pattern(
        "one note a bar, held — for breakdowns and pads",
        (0.0,), 3.9,
    ),
    "octave": Pattern(
        "offbeat with every other note an octave up",
        (0.5, 1.5, 2.5, 3.5), 0.42, octave_lift=(1, 3),
    ),
    "halftime": Pattern(
        "two long notes a bar, sitting under a busy top",
        (0.0, 2.0), 1.9,
    ),
    "sixteenth": Pattern(
        "a full sixteenth-note run, relentless",
        tuple(i * 0.25 for i in range(16)), 0.2,
    ),
}


def root_at(entries: list[tuple[float, float, object]], beat: float) -> int | None:
    """The pitch class of whichever chord is sounding at this moment."""
    for start, length, chord in entries:
        if start - 1e-6 <= beat < start + length:
            return getattr(chord, "root_pc", None)
    return entries[-1][2].root_pc if entries else None


def place(pitch_class: int, low: int, high: int, near: int | None) -> int:
    candidates = [p for p in range(low, high + 1) if p % 12 == pitch_class % 12]
    if not candidates:
        return max(low, min(high, pitch_class))
    return min(candidates, key=lambda p: abs(p - (near if near is not None else (low + high) // 2)))


def line(pattern: str, entries: list[tuple[float, float, object]], bars: int, *, low: int = 28, high: int = 50, velocity: int = 100, accent: int = 12) -> list[Note]:
    """A bassline in the given rhythm, following the progression's roots.

    The first hit of each bar is accented, because an unaccented bassline reads
    as a texture rather than as a groove.
    """
    if pattern not in PATTERNS:
        raise KeyError(pattern)
    if not entries:
        raise ValueError("A bassline needs a chord progression to follow")
    shape = PATTERNS[pattern]
    notes: list[Note] = []
    previous: int | None = None
    length = bars * 4
    for bar in range(bars):
        for index, position in enumerate(shape.hits):
            start = bar * 4 + position
            if start >= length - 1e-9:
                continue
            root = root_at(entries, start)
            if root is None:
                continue
            pitch = place(root, low, high, previous)
            if index in shape.octave_lift and pitch + 12 <= high + 12:
                pitch += 12
            else:
                previous = pitch
            notes.append(Note(
                pitch=max(0, min(127, pitch)),
                start=round(start, 4),
                duration=round(min(shape.duration, length - start), 4),
                velocity=max(1, min(127, velocity + (accent if index == 0 else 0))),
            ))
    return notes


def describe(pattern: str) -> str:
    return f"{pattern}: {PATTERNS[pattern].meaning}"
