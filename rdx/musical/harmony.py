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

from ..domain import PITCH_CLASSES, SCALE_STEPS, Note

MAJOR = SCALE_STEPS["major"]
MINOR = SCALE_STEPS["minor"]
ROMAN = ("I", "II", "III", "IV", "V", "VI", "VII")

# Chord tones above the root, by quality. The triads are the shapes a
# progression is built from; the rest are colours added on request, because a
# seventh on every chord is a different genre rather than a better voicing.
QUALITIES = {
    "major": (0, 4, 7),
    "minor": (0, 3, 7),
    "diminished": (0, 3, 6),
    "sus2": (0, 2, 7),
    "sus4": (0, 5, 7),
    "major7": (0, 4, 7, 11),
    "minor7": (0, 3, 7, 10),
    "dominant7": (0, 4, 7, 10),
    "half_diminished": (0, 3, 6, 10),
    "major9": (0, 4, 7, 11, 14),
    "minor9": (0, 3, 7, 10, 14),
    "add9": (0, 2, 4, 7),
    "minor_add9": (0, 2, 3, 7),
    "sixth": (0, 4, 7, 9),
    "minor_sixth": (0, 3, 7, 9),
    "dominant9": (0, 4, 7, 10, 14),
    "minor_major7": (0, 3, 7, 11),
    "diminished7": (0, 3, 6, 9),
}

TRIADS = ("major", "minor", "diminished")

# Colours that are the same shape wherever they land.
FIXED_COLOURS: dict[str, dict[str, str]] = {
    "add9": {"major": "add9", "minor": "minor_add9", "diminished": "diminished"},
    "sixth": {"major": "sixth", "minor": "minor_sixth", "diminished": "diminished"},
    "plain": {"major": "major", "minor": "minor", "diminished": "diminished"},
}

# A suspension replaces the third with the note two or four scale steps up —
# and only some degrees produce a usable one. The fourth above the VI of a
# minor key is a tritone, not a suspension, so those chords are left as triads
# rather than given a chord that would sound like a mistake.
SUSPENSIONS = {"sus2": (1, 2), "sus4": (3, 5)}

# Sevenths are not. The seventh of a chord comes from the key, not from the
# triad: in A minor the VII is G7 and the III is Cmaj7, both major triads. A
# lookup that gave every major triad a major seventh would put a wrong note in
# the most common cadence in the genre, so the interval is worked out instead.
SEVENTHS = {
    ("major", 11): "major7", ("major", 10): "dominant7",
    ("minor", 10): "minor7", ("minor", 11): "minor_major7",
    ("diminished", 10): "half_diminished", ("diminished", 9): "diminished7",
}
NINTHS = {"major7": "major9", "dominant7": "dominant9", "minor7": "minor9", "minor_major7": "minor9", "half_diminished": "half_diminished", "diminished7": "diminished7"}

COLOURS = ("seventh", "ninth", *SUSPENSIONS, *FIXED_COLOURS)

# A sixth on a minor chord is a Dorian sixth — F# over A minor — which is
# outside the natural minor scale. It is a real and common colour in dance
# music, so it stays, but it is the one colour that borrows, and RDX says so
# rather than letting a note appear from nowhere.
BORROWS = {"sixth": "The sixth is borrowed from Dorian on minor chords."}


def step_interval(degree: int, steps_up: int, scale: str) -> int:
    """The distance in semitones to a note a given number of scale steps up."""
    ladder = steps_of(scale)
    return (ladder[(degree + steps_up) % 7] - ladder[degree]) % 12


def seventh_interval(degree: int, scale: str) -> int:
    """How far the key's own seventh sits above a chord's root, in semitones."""
    return step_interval(degree, 6, scale)


def suspension(degree: int, scale: str, kind: str) -> str | None:
    """The suspension this degree supports in this key, if it supports one."""
    steps_up, wanted = SUSPENSIONS[kind]
    return kind if step_interval(degree, steps_up, scale) == wanted else None


def steps_of(scale: str) -> tuple[int, ...]:
    return SCALE_STEPS[scale]

SUFFIXES = {
    "major": "", "minor": "m", "diminished": "dim", "sus2": "sus2", "sus4": "sus4",
    "major7": "maj7", "minor7": "m7", "dominant7": "7", "half_diminished": "m7b5",
    "major9": "maj9", "minor9": "m9", "add9": "add9", "minor_add9": "m(add9)",
    "sixth": "6", "minor_sixth": "m6", "dominant9": "9", "minor_major7": "m(maj7)", "diminished7": "dim7",
}

# Roman numerals carry the quality in the case of the numeral itself, so the
# suffix must not repeat it: i7, not im7, and never "maj7" trimmed to "aj7".
NUMERAL_SUFFIXES = {
    "major": "", "minor": "", "diminished": "", "sus2": "sus2", "sus4": "sus4",
    "major7": "maj7", "minor7": "7", "dominant7": "7", "half_diminished": "ø7",
    "major9": "maj9", "minor9": "9", "add9": "add9", "minor_add9": "add9",
    "sixth": "6", "minor_sixth": "6", "dominant9": "9", "minor_major7": "(maj7)", "diminished7": "°7",
}


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
        return PITCH_CLASSES[self.root_pc] + SUFFIXES[self.quality]

    @property
    def triad(self) -> str:
        """The plain shape underneath, so a colour can be applied or removed."""
        if self.quality in TRIADS:
            return self.quality
        return "diminished" if self.quality == "half_diminished" else "minor" if (0, 3) == self.intervals[:2] or self.quality.startswith("minor") else "major"

    def coloured(self, colour: str, scale: str = "minor") -> "Chord":
        """The same chord with an extension added, or taken back to its triad."""
        if colour in FIXED_COLOURS:
            return Chord(self.degree, self.root_pc, FIXED_COLOURS[colour][self.triad])
        if colour in SUSPENSIONS:
            quality = suspension(self.degree, scale, colour)
            return Chord(self.degree, self.root_pc, quality) if quality else self
        if colour not in {"seventh", "ninth"}:
            raise KeyError(colour)
        seventh = SEVENTHS.get((self.triad, seventh_interval(self.degree, scale)))
        if seventh is None:  # an interval the key does not produce; leave it alone
            return self
        return Chord(self.degree, self.root_pc, seventh if colour == "seventh" else NINTHS[seventh])

    @property
    def numeral(self) -> str:
        numeral = ROMAN[self.degree]
        lower = self.triad in {"minor", "diminished"}
        return (numeral.lower() if lower else numeral) + ("°" if self.triad == "diminished" else "") + NUMERAL_SUFFIXES[self.quality]


def key_pc(key: str) -> int:
    return PITCH_CLASSES.index(key)


def diatonic(key: str, scale: str) -> list[Chord]:
    """The seven triads of the key, plus the major V that minor keys borrow."""
    steps = steps_of(scale)
    root = key_pc(key)
    chords = []
    for degree in range(7):
        pcs = [(steps[(degree + i) % 7] + (12 if degree + i >= 7 else 0)) for i in (0, 2, 4)]
        third, fifth = pcs[1] - pcs[0], pcs[2] - pcs[0]
        quality = "major" if (third, fifth) == (4, 7) else "minor" if (third, fifth) == (3, 7) else "diminished"
        chords.append(Chord(degree, (root + steps[degree]) % 12, quality))
    if quality_of(chords[4]) == "minor":
        # The harmonic-minor V that this music leans on going into the tonic.
        # Offered for any mode whose fifth degree is minor, which is what makes
        # the cadence want it in the first place.
        chords.append(Chord(4, (root + steps[4]) % 12, "major"))
    return chords


def quality_of(chord: Chord) -> str:
    return chord.quality


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


# How much better a suspension has to score than the plain triad before RDX
# hears one. A triad is the default reading of a melody; a sus chord is a
# claim that the third is deliberately missing, and it should have to earn it.
SUSPENSION_MARGIN = 1.12


def sus_candidates(chords: list[Chord], scale: str) -> list[Chord]:
    """The suspensions available in this key, as chords the search can pick.

    Making them candidates rather than a post-hoc override means the same
    scoring decides: a melody that leans on the fourth and never touches the
    third scores higher as sus4 because the fourth is a chord tone there and a
    wrong note in the triad. Nothing special-cases it.
    """
    found: list[Chord] = []
    for chord in chords:
        if chord.quality not in TRIADS:
            continue
        for kind in SUSPENSIONS:
            if suspension(chord.degree, scale, kind):
                found.append(Chord(chord.degree, chord.root_pc, kind))
    return found


def colour_progression(entries: list[tuple[float, float, Chord]], colour: str, scale: str = "minor") -> list[tuple[float, float, Chord]]:
    """Add the same extension across a progression, or take it back to triads."""
    if colour not in COLOURS:
        raise KeyError(colour)
    return [(start, length, chord.coloured(colour, scale)) for start, length, chord in entries]


def progression(notes: list[Note], bars: int, key: str, scale: str, span: float = 4.0, sus: bool = True) -> list[tuple[float, float, Chord]]:
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
    suspensions = sus_candidates(chords, scale) if sus else []
    for start, inside in segment_notes(notes, bars, span):
        if not inside:
            chosen = previous or tonic
        else:
            chosen = max(chords, key=lambda c: score_chord(c, inside, previous))
            if suspensions:
                best = max(suspensions, key=lambda c: score_chord(c, inside, previous))
                triad_score = score_chord(chosen, inside, previous)
                if triad_score > 0 and score_chord(best, inside, previous) > triad_score * SUSPENSION_MARGIN:
                    chosen = best
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


# --- progressions asked for rather than hummed ------------------------------

# The progressions this music is actually built on, as scale degrees. Written
# as numbers rather than symbols so they transpose to any key for free, and
# named so a producer can ask for one without humming it first.
NAMED_PROGRESSIONS: dict[str, tuple[str, tuple[int, ...]]] = {
    "trance": ("the one almost every uplifting track sits on", (0, 5, 2, 6)),
    "andalusian": ("the descending four that sounds inevitable", (0, 6, 5, 4)),
    "epic": ("rocks between the tonic and the two above it", (0, 6, 5, 6)),
    "pop": ("the four chords, starting away from home", (5, 3, 0, 4)),
    "melancholy": ("falls to the fourth and climbs back", (0, 3, 6, 2)),
    "driving": ("stays close to the tonic and pushes", (0, 6, 0, 4)),
    "suspense": ("never resolves, which is what makes it work under a build", (0, 4, 5, 4)),
    "lift": ("steps upward the whole way", (5, 6, 0, 2)),
    "classic": ("the oldest cadence there is", (0, 3, 4, 0)),
}

NUMERALS = {"i": 0, "ii": 1, "iii": 2, "iv": 3, "v": 4, "vi": 5, "vii": 6}


def parse_progression(text: str) -> list[int]:
    """Read "i-VI-III-VII" or "1 6 3 7" as scale degrees.

    Case is ignored: the key already decides whether the third degree is major
    or minor, and a numeral that disagrees with the key would be a borrowed
    chord rather than a typo, which is a separate request.
    """
    parts = [p.strip() for p in text.replace("|", "-").replace(",", "-").replace(" ", "-").split("-") if p.strip()]
    if not 1 < len(parts) <= 16:
        raise ValueError("A progression is between two and sixteen chords")
    degrees = []
    for part in parts:
        if part.isdigit() and 1 <= int(part) <= 7:
            degrees.append(int(part) - 1)
        elif part.lower() in NUMERALS:
            degrees.append(NUMERALS[part.lower()])
        else:
            raise ValueError(f"'{part}' is not a chord degree. Use I to VII, or 1 to 7.")
    return degrees


def from_degrees(degrees: list[int], bars: int, key: str, scale: str, span: float = 4.0) -> list[tuple[float, float, Chord]]:
    """Lay a progression out across a section, repeating it to fill the space."""
    if not degrees:
        raise ValueError("There are no chords in that progression")
    chords = diatonic(key, scale)
    by_degree = {chord.degree: chord for chord in chords if chord.quality in TRIADS}
    total = bars * 4
    entries: list[tuple[float, float, Chord]] = []
    start = 0.0
    index = 0
    while start < total - 1e-9:
        chord = by_degree[degrees[index % len(degrees)] % 7]
        entries.append((round(start, 4), min(span, total - start), chord))
        start += span
        index += 1
    return entries


def named(name: str, bars: int, key: str, scale: str, span: float = 4.0) -> list[tuple[float, float, Chord]]:
    if name not in NAMED_PROGRESSIONS:
        raise KeyError(name)
    return from_degrees(list(NAMED_PROGRESSIONS[name][1]), bars, key, scale, span)
