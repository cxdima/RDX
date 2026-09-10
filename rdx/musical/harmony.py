"""Turning a hummed line into a chord progression.

Two things can arrive from the microphone: the root of each chord held out
one at a time, or a melody that implies harmony underneath. RDX decides which
it received from the shape of the notes rather than asking, then builds the
progression accordingly.

The chord-choosing is a scored search, not a lookup, so it can explain why it
picked what it picked and a producer can argue with the weights.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..domain import Note

MAJOR = (0, 2, 4, 5, 7, 9, 11)
MINOR = (0, 2, 3, 5, 7, 8, 10)
PITCH_CLASSES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
ROMAN = ("I", "II", "III", "IV", "V", "VI", "VII")

# Chord tones above the root, by quality.
QUALITIES = {"major": (0, 4, 7), "minor": (0, 3, 7), "diminished": (0, 3, 6), "sus4": (0, 5, 7)}


@dataclass(frozen=True)
class Chord:
    degree: int  # 0-based scale degree
    root_pc: int  # pitch class 0-11
    quality: str

    @property
    def intervals(self) -> tuple[int, ...]:
        return QUALITIES[self.quality]

    @property
    def pitch_classes(self) -> set[int]:
        return {(self.root_pc + i) % 12 for i in self.intervals}

    @property
    def symbol(self) -> str:
        suffix = {"major": "", "minor": "m", "diminished": "dim", "sus4": "sus4"}[self.quality]
        return PITCH_CLASSES[self.root_pc] + suffix

    @property
    def numeral(self) -> str:
        numeral = ROMAN[self.degree]
        return numeral.lower() + ("°" if self.quality == "diminished" else "") if self.quality in {"minor", "diminished"} else numeral


def key_pc(key: str) -> int:
    return PITCH_CLASSES.index(key)


def diatonic(key: str, scale: str) -> list[Chord]:
    """The seven triads of the key, plus the major V that minor keys borrow."""
    steps = MINOR if scale == "minor" else MAJOR
    root = key_pc(key)
    chords = []
    for degree in range(7):
        pcs = [(steps[(degree + i) % 7] + (12 if degree + i >= 7 else 0)) for i in (0, 2, 4)]
        third, fifth = pcs[1] - pcs[0], pcs[2] - pcs[0]
        quality = "major" if (third, fifth) == (4, 7) else "minor" if (third, fifth) == (3, 7) else "diminished"
        chords.append(Chord(degree, (root + steps[degree]) % 12, quality))
    if scale == "minor":
        # Harmonic-minor V: the dominant trance leans on going into the tonic.
        chords.append(Chord(4, (root + steps[4]) % 12, "major"))
    return chords


def notes_per_bar(notes: list[Note], bars: int) -> float:
    return len(notes) / max(bars, 1)


def looks_like_roots(notes: list[Note], bars: int) -> bool:
    """Decide whether a hum gave chord roots or a melody.

    Roots arrive slowly and are held; a melody moves. Judged on how many notes
    per bar there are and how long they last, not on the pitches themselves.
    """
    if not notes:
        return False
    average = sum(n.duration for n in notes) / len(notes)
    return notes_per_bar(notes, bars) <= 2.0 and average >= 0.9


def segment_notes(notes: list[Note], bars: int, span: float) -> list[tuple[float, list[Note]]]:
    """Group notes into equal spans, keeping the portion inside each span."""
    segments = []
    total = bars * 4
    start = 0.0
    while start < total - 1e-9:
        end = min(start + span, total)
        inside = []
        for note in notes:
            overlap = min(note.start + note.duration, end) - max(note.start, start)
            if overlap > 1e-6:
                inside.append(note.model_copy(update={"start": max(note.start, start), "duration": overlap}))
        segments.append((start, inside))
        start = end
    return segments


def score_chord(chord: Chord, notes: list[Note], previous: Chord | None) -> float:
    """How well a chord explains a span of melody.

    Weights, in plain terms: a note sitting on the chord's root counts most,
    other chord tones count well, scale tones are tolerated, anything outside
    the chord costs. Movement away from the previous root is rewarded a little
    so the progression goes somewhere instead of sitting still.
    """
    score = 0.0
    for note in notes:
        pc = note.pitch % 12
        weight = note.duration * (1.6 if note.start % 4 < 0.51 else 1.0)  # downbeats matter more
        if pc == chord.root_pc:
            score += 3.0 * weight
        elif pc in chord.pitch_classes:
            score += 2.0 * weight
        else:
            score -= 1.2 * weight
    if previous is not None:
        distance = min((chord.root_pc - previous.root_pc) % 12, (previous.root_pc - chord.root_pc) % 12)
        score += 0.9 if distance in (5, 7) else 0.5 if distance in (2, 3, 4) else -0.6 if distance == 0 else 0.0
    return score


def nearest_chord(pitch: int, chords: list[Chord]) -> Chord:
    """The chord whose root is closest to a hummed note, root match preferred."""
    pc = pitch % 12
    exact = [c for c in chords if c.root_pc == pc]
    if exact:
        return min(exact, key=lambda c: c.quality != "minor")  # prefer the plain triad over borrowed V
    return min(chords, key=lambda c: min((c.root_pc - pc) % 12, (pc - c.root_pc) % 12))


def progression(notes: list[Note], bars: int, key: str, scale: str, span: float = 4.0) -> list[tuple[float, float, Chord]]:
    """Infer a chord progression from a hummed line.

    Returns (start_beat, length_beats, chord) covering the whole section.
    """
    if not notes:
        raise ValueError("There are no notes to build a progression from")
    chords = diatonic(key, scale)
    tonic = chords[0]
    result: list[tuple[float, float, Chord]] = []
    previous: Chord | None = None
    if looks_like_roots(notes, bars):
        # Each hummed note names a chord; it lasts until the next one starts.
        ordered = sorted(notes, key=lambda n: n.start)
        for index, note in enumerate(ordered):
            end = ordered[index + 1].start if index + 1 < len(ordered) else bars * 4
            chosen = nearest_chord(note.pitch, chords)
            result.append((note.start, max(end - note.start, 0.25), chosen))
            previous = chosen
        if result and result[0][0] > 0.01:  # fill the gap before the first hum
            start, length, chord = result[0]
            result[0] = (0.0, length + start, chord)
        return result
    for start, inside in segment_notes(notes, bars, span):
        if not inside:
            chosen = previous or tonic
        else:
            chosen = max(chords, key=lambda c: score_chord(c, inside, previous))
        result.append((start, span, chosen))
        previous = chosen
    return result


def voice(entries: list[tuple[float, float, Chord]], *, low: int = 48, high: int = 72, voices: int = 3, velocity: int = 72, legato: float = 0.98) -> list[Note]:
    """Voice a progression with smooth movement between chords.

    Each chord is placed in the register, then the octave arrangement closest
    to the previous chord is chosen so the parts glide rather than jump.
    """
    notes: list[Note] = []
    previous: list[int] = []
    for start, length, chord in entries:
        candidates: list[list[int]] = []
        for inversion in range(len(chord.intervals)):
            pitches = []
            order = chord.intervals[inversion:] + tuple(i + 12 for i in chord.intervals[:inversion])
            base = low + ((chord.root_pc - low) % 12)
            for step in range(voices):
                interval = order[step % len(order)] + 12 * (step // len(order))
                pitches.append(base + interval)
            while max(pitches) > high and min(pitches) - 12 >= low - 12:
                pitches = [p - 12 for p in pitches]
            candidates.append(pitches)
        if previous:
            best = min(candidates, key=lambda c: sum(abs(a - b) for a, b in zip(sorted(c), sorted(previous))))
        else:
            best = candidates[0]
        for pitch in best:
            notes.append(Note(pitch=max(0, min(127, pitch)), start=round(start, 4), duration=round(max(length * legato, 0.125), 4), velocity=velocity))
        previous = best
    return sorted(notes, key=lambda n: (n.start, n.pitch))


def describe(entries: list[tuple[float, float, Chord]]) -> str:
    """A plain reading of the progression, e.g. 'Am - F - C - G (i - VI - III - VII)'."""
    unique: list[Chord] = []
    for _, _, chord in entries:
        if not unique or unique[-1] != chord:
            unique.append(chord)
    shown = unique[:8]
    symbols = " - ".join(c.symbol for c in shown)
    numerals = " - ".join(c.numeral for c in shown)
    return f"{symbols} ({numerals})" + ("..." if len(unique) > len(shown) else "")
