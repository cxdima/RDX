"""Writing one part against another, instead of against the key alone.

Every generator RDX had worked from the project key and nothing else. That is
why *"the bass should follow the chords"* and *"give the bass a counter-rhythm
to the kick"* had no answer: the bass generator could not see the chords, and
nothing could see the drums.

An arrangement is relationships. The bass plays the root of whatever the chords
are doing; the counter-melody moves when the lead holds; the plucks land in the
gaps the kick leaves. This module reads one part and writes another from it, so
the two are related by construction rather than by luck.

Everything here takes notes and returns notes. What each function claims is
testable in one line: *follow* must put the bass on the chord root at every
chord change; *counter* must land where the source does not; *harmonise* must
stay in the key at the requested interval.
"""
from __future__ import annotations

import random

from ..domain import Note
from .melody import position_in, scale_pitches, step_by
from .sidechain import TRIGGERS

# Where each part naturally sits, so a generated line lands in the right octave.
REGISTERS = {"bass": (28, 52), "chords": (48, 74), "pad": (48, 76), "lead": (60, 88)}


def register(role: str) -> tuple[int, int]:
    return REGISTERS.get(role, (48, 76))


def place(pitch_class: int, low: int, high: int, near: int | None = None) -> int:
    """Put a pitch class in a register, nearest to where the part just was."""
    candidates = [p for p in range(low, high + 1) if p % 12 == pitch_class % 12]
    if not candidates:
        return max(low, min(high, pitch_class))
    target = near if near is not None else (low + high) // 2
    return min(candidates, key=lambda p: abs(p - target))


def chord_changes(notes: list[Note], length: float) -> list[tuple[float, float, int]]:
    """Where the harmony changes, and the root it moves to.

    The lowest note sounding at each moment is taken as the root, which is what
    a bass player listens for and is right for the voicings RDX writes.
    """
    if not notes:
        return []
    moments = sorted({round(n.start, 4) for n in notes})
    changes: list[tuple[float, float, int]] = []
    for index, moment in enumerate(moments):
        sounding = [n for n in notes if n.start <= moment + 1e-6 < n.start + n.duration]
        if not sounding:
            continue
        root = min(sounding, key=lambda n: n.pitch).pitch % 12
        end = moments[index + 1] if index + 1 < len(moments) else length
        if changes and changes[-1][2] == root:
            start, _, previous = changes[-1]
            changes[-1] = (start, end, previous)
        else:
            changes.append((moment, end, root))
    return [(start, max(end - start, 0.125), root) for start, end, root in changes]


def follow(source: list[Note], length: float, *, role: str = "bass", rhythm: list[Note] | None = None, velocity: int = 92) -> list[Note]:
    """Write a part that plays the roots of another part's harmony.

    With a rhythm given, the new part keeps that rhythm and only its pitches
    change — which is how "keep the bassline but follow the new chords" works
    without rewriting the groove.
    """
    changes = chord_changes(source, length)
    if not changes:
        raise ValueError("There is nothing to follow in that part")
    low, high = register(role)
    written: list[Note] = []
    if rhythm:
        previous = None
        for note in sorted(rhythm, key=lambda n: n.start):
            root = next((r for start, span, r in changes if start <= note.start < start + span), changes[-1][2])
            pitch = place(root, low, high, previous)
            written.append(note.model_copy(update={"id": None, "pitch": pitch}, deep=True))
            previous = pitch
        return [Note(pitch=n.pitch, start=n.start, duration=n.duration, velocity=n.velocity) for n in written]
    previous = None
    for start, span, root in changes:
        pitch = place(root, low, high, previous)
        written.append(Note(pitch=pitch, start=round(start, 4), duration=round(min(span, length - start), 4), velocity=velocity))
        previous = pitch
    return written


def gaps(source: list[Note], length: float, grid: float = 0.5) -> list[float]:
    """The grid positions where the source part is not playing."""
    busy = set()
    for note in source:
        step = 0.0
        while step < length:
            if note.start - grid / 2 < step < note.start + max(note.duration, grid / 2):
                busy.add(round(step, 4))
            step += grid
    return [round(step, 4) for step in [i * grid for i in range(int(length / grid))] if round(step, 4) not in busy]


def counter(source: list[Note], length: float, *, pitches: list[int] | None = None, role: str = "lead", grid: float = 0.5, density: float = 0.6, key: str = "A", scale: str = "minor", seed: int = 0, velocity: int = 78, against: str | None = None) -> list[Note]:
    """A part that plays in the spaces another part leaves.

    This is what "give it a counter-rhythm to the kick" means: not a different
    pattern that happens to coexist, but one placed where the first is silent.

    `against` names a single drum voice, because a counter-rhythm to a whole
    kit is not a musical idea — a kit with sixteenth hats leaves no gaps at
    all. Answering the kick is the request people actually make.
    """
    if not 0 < density <= 1:
        raise ValueError("A counter-rhythm has to place some notes")
    if against is not None:
        voice = TRIGGERS.get(against)
        if against not in TRIGGERS:
            raise ValueError(f"There is no '{against}' drum voice to answer")
        source = [n for n in source if voice is None or n.pitch == voice]
        if not source:
            raise ValueError(f"That part has no {against} to answer")
    openings = gaps(source, length, grid)
    if not openings:
        raise ValueError("That part is playing constantly; there is no space to answer it")
    rng = random.Random(f"counter:{seed}:{density}")
    low, high = register(role)
    ladder = scale_pitches(key, scale, low, high)
    if not ladder:
        raise ValueError("There is no room in that register")
    available = sorted({p % 12 for p in (pitches or [])}) or None
    written: list[Note] = []
    index = len(ladder) // 2
    for step in openings:
        if rng.random() > density:
            continue
        if available:
            pitch = place(rng.choice(available), low, high, ladder[index])
        else:
            index = max(0, min(len(ladder) - 1, index + rng.choice([-2, -1, 1, 2])))
            pitch = ladder[index]
        written.append(Note(pitch=pitch, start=step, duration=round(min(grid * 0.9, length - step), 4), velocity=velocity + rng.randint(-8, 8)))
        index = position_in(ladder, pitch)
    if not written:
        raise ValueError("Nothing was placed; try a higher density")
    return written


def harmonise(source: list[Note], *, degrees: int = 2, key: str = "A", scale: str = "minor", velocity_drop: int = 12) -> list[Note]:
    """A second line a fixed number of scale degrees from the first.

    In degrees, not semitones: a third above in the key is sometimes four
    semitones and sometimes three, and using a constant interval is what makes
    a harmony line sound wrong in exactly one bar out of four.
    """
    if not isinstance(degrees, int) or not 1 <= abs(degrees) <= 7:
        raise ValueError("A harmony line sits one to seven scale degrees away")
    ladder = scale_pitches(key, scale)
    return [
        Note(pitch=max(0, min(127, step_by(ladder, note.pitch, degrees))), start=note.start, duration=note.duration, velocity=max(1, note.velocity - velocity_drop))
        for note in sorted(source, key=lambda n: (n.start, n.pitch))
    ]


def octaves(source: list[Note], *, direction: int = -1) -> list[Note]:
    """The same line doubled an octave away, dropping anything unplayable."""
    doubled = [note.model_copy(update={"id": None}, deep=True) for note in source]
    return [Note(pitch=n.pitch + 12 * direction, start=n.start, duration=n.duration, velocity=n.velocity) for n in doubled if 0 <= n.pitch + 12 * direction <= 127]


RELATIONS = {"follow": "plays the roots of another part's harmony", "counter": "plays in the spaces another part leaves", "harmonise": "adds a second line a set distance away in the key", "octave": "doubles the part an octave away"}
