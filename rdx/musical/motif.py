"""Melodies that are composed rather than generated.

A melody is a short idea, repeated often enough that you remember it and varied
often enough that you don't get bored. RDX's first note generator did neither:
it drew eight random scale degrees, replayed them every bar, and punched random
holes in the result. Every bar differed from the last in a way no ear could
follow, and no bar was ever the *answer* to another. That is what "it sounds
simple" means — not too few notes, but nothing to hold on to.

So a melody here is three decisions a producer actually makes:

  a **cell**   the rhythm of the idea — one bar of it, silences included
  a **shape**  where the idea goes, as steps through the scale
  a **form**   what happens to the idea across eight bars: stated, repeated,
               sequenced up, left open as a question, lifted to a peak, resolved

and one rule underneath all three: **a note on a whole beat is a chord tone.**
That single constraint is most of the difference between a line that sits inside
the harmony and one that argues with it.

Everything is expressed in scale degrees relative to the chord that is sounding,
so a melody cannot leave the key and cannot drift off the progression. Positions
are in quarter notes from the start of a bar.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..domain import PITCH_CLASSES, SCALE_STEPS, Note


@dataclass(frozen=True)
class Cell:
    """The rhythm of one bar of the idea, and how long each note rings."""

    meaning: str
    hits: tuple[float, ...]
    hold: tuple[float, ...]


CELLS: dict[str, Cell] = {
    "pluck": Cell(
        "sixteenths with gaps — the trance pluck that carries a drop",
        (0.0, 0.25, 0.75, 1.5, 1.75, 2.25, 3.0, 3.5),
        (0.22, 0.22, 0.22, 0.22, 0.22, 0.22, 0.45, 0.45),
    ),
    "anthem": Cell(
        "long notes over the bar — the breakdown melody you can sing back",
        (0.0, 1.5, 2.5),
        (1.4, 0.9, 1.4),
    ),
    "call": Cell(
        "three notes and then silence, so the next bar has room to answer",
        (0.0, 0.5, 1.0),
        (0.45, 0.45, 1.3),
    ),
    "drive": Cell(
        "unbroken eighths, pushing rather than singing",
        (0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5),
        (0.45,) * 8,
    ),
    "push": Cell(
        "every note lands late — syncopation is what makes a line move",
        (0.5, 1.25, 2.0, 2.75, 3.5),
        (0.7, 0.7, 0.7, 0.7, 0.45),
    ),
    "roll": Cell(
        "a run of sixteenths into a held note — the acid line",
        (0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.5),
        (0.22, 0.22, 0.22, 0.22, 0.22, 0.22, 0.22, 1.4),
    ),
    "stab": Cell(
        "two notes a bar, held wide open — a lead that answers the drums",
        (0.0, 2.0),
        (1.7, 1.7),
    ),
}

# Where the idea goes, in scale steps from wherever it starts. Cycled over the
# cell's hits, so a long cell states the shape more than once.
SHAPES: dict[str, tuple[int, ...]] = {
    "climb": (0, 1, 2, 3),
    "fall": (0, -1, -2, -3),
    "arch": (0, 2, 3, 1),
    "turn": (0, 1, 0, -1),
    "hook": (0, 2, 1, 4),
    "leap": (0, 4, 2, 5),
    "hover": (0, 1, -1, 0),
    # Eight steps, so a busy cell states the idea once across the bar rather
    # than twice. A four-step shape over sixteen notes is an arpeggio; this is
    # a tune.
    "ascent": (0, 1, 2, 3, 4, 3, 2, 1),
    "wave": (0, 2, 1, 3, 2, 4, 3, 1),
    "question": (0, 1, 2, 1, 4, 3, 2, 4),
    "descent": (4, 3, 2, 1, 0, 1, 2, 0),
}

# What happens to the idea in a given bar.
#   state/repeat  the idea as it is — repetition is what makes it memorable
#   sequence      the same shape one scale step higher than the bar before
#   invert        the same shape upside down
#   open          ends on the fifth: a question, left hanging
#   peak          the bar that reaches higher than any other in the phrase
#   close         ends on the tonic and holds: the answer
#   rest          silence, which a melody needs as much as it needs notes
DEVELOPMENTS = ("state", "repeat", "sequence", "invert", "open", "peak", "close", "rest")

FORMS: dict[str, tuple[str, ...]] = {
    # Two bars of idea, two more that repeat it and leave it open, then a
    # sequence that climbs and a peak that resolves. The trance eight.
    "trance": ("state", "repeat", "state", "open", "sequence", "sequence", "peak", "close"),
    "anthem": ("state", "repeat", "sequence", "open", "state", "repeat", "peak", "close"),
    "answer": ("state", "rest", "repeat", "rest", "sequence", "rest", "peak", "close"),
    "driving": ("state", "repeat", "sequence", "sequence", "invert", "repeat", "peak", "close"),
    "rising": ("state", "sequence", "sequence", "sequence", "state", "sequence", "peak", "close"),
    # What a generator does instead of a composer, kept so the two can be
    # compared rather than argued about.
    "loop": ("state",) * 8,
}


@dataclass
class Placed:
    """One note before it knows its pitch, so a phrase can be revised as a whole."""

    bar: int
    development: str
    start: float
    degree: int
    hold: float
    strong: bool
    chord: object


def weight(position: float) -> int:
    """How structurally important a position in the bar is."""
    if abs(position % 1) < 1e-9:
        return 3 if abs(position % 2) < 1e-9 else 2
    return 1 if abs(position % 0.5) < 1e-9 else 0


def thinned(cell: Cell, density: float) -> list[int]:
    """Which hits survive at this density — the strong ones, always the first."""
    if density >= 1:
        return list(range(len(cell.hits)))
    order = sorted(range(len(cell.hits)), key=lambda i: (-weight(cell.hits[i]), i))
    return sorted(order[: max(1, round(len(cell.hits) * density))])


def pitch_at(degree: int, key: str, scale: str, low: int) -> int:
    """A scale degree as a pitch, counting up from the lowest root in range."""
    steps = SCALE_STEPS[scale]
    size = len(steps)
    root = PITCH_CLASSES.index(key)
    base = low + ((root - low) % 12)
    octave, within = divmod(degree, size)
    return base + 12 * octave + steps[within]


def chord_tone(pitch: int, chord: object) -> int:
    """The nearest pitch belonging to the chord, so strong beats land inside it."""
    classes = getattr(chord, "pitch_classes", None)
    if not classes or pitch % 12 in classes:
        return pitch
    # Only candidates that actually belong to the chord. Taking the nearest
    # pitch without checking that is how a melody ends up a semitone outside
    # its own key while every test about the chords still passes.
    #
    # Two semitones at most. Further than that and the same degree lands four
    # semitones apart in two bars that are supposed to be the same idea — the
    # ear hears a different note rather than the same one recoloured. A degree
    # with no chord tone that close stays where it is and sounds as a second or
    # a seventh over the chord, which is a colour, not a mistake.
    inside = [pitch + step for step in (1, -1, 2, -2) if (pitch + step) % 12 in classes]
    return min(inside, key=lambda p: (abs(p - pitch), -p)) if inside else pitch


def chord_at(entries: list[tuple[float, float, object]], beat: float) -> object | None:
    for start, length, chord in entries:
        if start - 1e-6 <= beat < start + length:
            return chord
    return entries[-1][2] if entries else None


def develop(development: str, shape: tuple[int, ...], carried: int) -> tuple[tuple[int, ...], int]:
    """This bar's shape, and the shift to carry into the next one."""
    if development in {"state", "repeat", "peak"}:
        return shape, 0
    if development == "sequence":
        step = carried + 1
        return tuple(offset + step for offset in shape), step
    if development == "invert":
        return tuple(-offset for offset in shape), 0
    if development in {"open", "close"}:
        return shape, carried
    raise KeyError(development)


def line(
    cell: str,
    shape: str,
    form: str,
    entries: list[tuple[float, float, object]],
    bars: int,
    *,
    key: str,
    scale: str,
    low: int = 60,
    high: int = 88,
    density: float = 1.0,
    velocity: int = 92,
    anchor: str = "key",
) -> list[Note]:
    """An eight-bar melody made from one idea, developed.

    `anchor` decides what a repeat means when the chord underneath has changed.
    Anchored to the **key**, the idea stays where it is and the new chord
    recolours it — which is the lift that carries most trance melodies, and the
    default. Anchored to the **chord**, the idea transposes along with the
    harmony, which sounds more like an arpeggio and less like a tune.

    Either way the phrase cannot drift off the progression: every note on beat
    one or three is pulled onto a tone of the chord that is sounding. Only those
    two — snapping every whole beat leaves no room for the passing notes a
    melody is mostly made of, and moves the same degree far enough between two
    bars that the ear stops hearing one idea.
    """
    if cell not in CELLS:
        raise KeyError(cell)
    if shape not in SHAPES:
        raise KeyError(shape)
    if form not in FORMS:
        raise KeyError(form)
    if not entries:
        raise ValueError("A melody needs a chord progression to follow")
    if not 0 < density <= 1:
        raise ValueError("Density must be above zero and at most one")
    if anchor not in {"key", "chord"}:
        raise ValueError("A melody is anchored either to the key or to the chord")

    rhythm, figure, plan = CELLS[cell], SHAPES[shape], FORMS[form]
    keep = thinned(rhythm, density)
    placed: list[Placed] = []
    carried = 0
    centre: float | None = None
    length = bars * 4

    for bar in range(bars):
        development = plan[bar % len(plan)]
        if development == "rest":
            carried = 0
            continue
        offsets, carried = develop(development, figure, carried)
        chord = chord_at(entries, bar * 4)
        home = getattr(chord, "degree", 0) if anchor == "chord" else 0
        # A cadence lands and then rings. Playing the full rhythm through to the
        # last sixteenth leaves the resolution no room to sound, and a phrase
        # that resolves on a passing note does not feel resolved at all.
        chosen = keep
        if development == "close":
            chosen = [h for h in keep if rhythm.hits[h] <= 2.0] or keep[:1]
        # Keep the whole phrase in the register it opened in. A bar is placed at
        # the nearest octave to that register rather than counted up from the
        # tonic: the arithmetic answer puts a chord on the seventh degree a
        # tenth above the bar before it, and a line that leaps an octave every
        # other bar is not one line.
        octaves = 0
        if chosen:
            here = home + sum(offsets[i % len(offsets)] for i in range(len(chosen))) / len(chosen)
            if centre is None:
                centre = here  # the register the phrase opens in, and keeps
            octaves = round((centre - here) / 7)
        for index, hit in enumerate(chosen):
            start = bar * 4 + rhythm.hits[hit]
            if start >= length - 1e-9:
                continue
            degree = home + offsets[index % len(offsets)] + octaves * 7
            hold = rhythm.hold[hit]
            if index == len(chosen) - 1:
                # The last note of the bar is what the ear remembers, so the
                # two cadence bars put it somewhere that means something.
                if development == "open":
                    degree = home + 4 + octaves * 7      # the fifth: a question
                elif development == "close":
                    # The tonic nearest where the line actually is, not the one
                    # counted from the bottom of the range.
                    degree = 7 * round((home + octaves * 7) / 7)
                    hold = 4 - rhythm.hits[hit]          # and it rings out the bar
            placed.append(Placed(bar, development, start, degree, hold, weight(rhythm.hits[hit]) == 3, chord))

    lift(placed)
    return render(placed, key, scale, low, high, velocity, length)


def lift(placed: list[Placed]) -> None:
    """Raise the peak bars until they really are the peak.

    A climax that is merely *near* the top of the phrase is not a climax. This
    moves the peak bars up whole scale steps — so they stay in key — until
    nothing else in the phrase reaches them.
    """
    peaks = [p for p in placed if p.development == "peak"]
    others = [p.degree for p in placed if p.development != "peak"]
    if not peaks or not others:
        return
    needed = max(others) - max(p.degree for p in peaks) + 1
    if needed > 0:
        for note in peaks:
            note.degree += needed


def render(placed: list[Placed], key: str, scale: str, low: int, high: int, velocity: int, length: float) -> list[Note]:
    pitches = []
    for note in placed:
        pitch = pitch_at(note.degree, key, scale, low)
        pitches.append(chord_tone(pitch, note.chord) if note.strong else pitch)
    # Move the phrase as one thing. Folding notes into range one at a time drops
    # single notes an octave and takes the shape apart — the climb that was the
    # point of the phrase turns into a jump downwards.
    shift = 0
    if pitches:
        while max(pitches) + shift > high and min(pitches) + shift - 12 >= low:
            shift -= 12
        while min(pitches) + shift < low and max(pitches) + shift + 12 <= high:
            shift += 12
    notes: list[Note] = []
    for note, raw in zip(placed, pitches):
        pitch = raw + shift
        # Louder on the downbeat and louder as the line climbs, which is how a
        # player phrases it without being asked to.
        accent = (10 if abs(note.start % 4) < 1e-9 else 0) + min(12, max(-6, (pitch - low) // 3))
        notes.append(Note(
            pitch=max(0, min(127, pitch)),
            start=round(note.start, 4),
            duration=round(min(note.hold, length - note.start), 4),
            velocity=max(1, min(127, velocity + accent)),
        ))
    return sorted(notes, key=lambda n: (n.start, n.pitch))


# What each development is called in the sentence the user reads. The words
# matter: this is the only account of the edit they get, and "sequenced up" says
# something a producer can check by ear where "sequence" does not.
TOLD = {
    "state": "stated",
    "repeat": "repeated",
    "sequence": "sequenced up",
    "invert": "inverted",
    "open": "left open on the fifth",
    "peak": "lifted to a peak",
    "close": "resolved home",
    "rest": "given a bar of silence",
}


def describe(cell: str, shape: str, form: str) -> str:
    story = " then ".join(dict.fromkeys(TOLD[move] for move in FORMS[form]))
    article = "an" if shape[0] in "aeiou" else "a"
    return f"{CELLS[cell].meaning}, on {article} {shape} shape, {story}"
