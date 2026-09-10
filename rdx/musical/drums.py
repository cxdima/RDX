"""Composable drum patterns.

A kit is chosen one layer at a time, so "a kick pattern with a double clap"
is a real request rather than a preset RDX happens not to have. Each layer is
independent: pick a kick, pick a clap, leave the rest alone.

Beat positions are in quarter notes from the start of a bar, so 0 is the
downbeat and 1.5 is the "and" of two. Defaults are trance/mainstage.
"""
from __future__ import annotations

import random

from ..domain import Note

KICK = 36
RIM = 37
SNARE = 38
CLAP = 39
HAT = 42
OPEN = 46
LOW_TOM, MID_TOM, HIGH_TOM = 45, 47, 50
CRASH, RIDE = 49, 51

# layer -> pattern name -> beats within one bar
LAYERS: dict[str, dict[str, list[float]]] = {
    "kick": {
        "four_floor": [0, 1, 2, 3],
        "broken": [0, 1.75, 2.5],
        "halftime": [0, 2.5],
        "rolling": [0, 1, 2, 3, 3.75],
        "none": [],
    },
    "clap": {
        # Two hits a thirty-second apart: the classic doubled clap.
        "double": [1, 1.125, 3, 3.125],
        "backbeat": [1, 3],
        "offbeat": [0.5, 1.5, 2.5, 3.5],
        "none": [],
    },
    "snare": {
        "backbeat": [1, 3],
        "third": [3],
        "none": [],
    },
    "hat": {
        "eighth": [i * 0.5 for i in range(8)],
        "sixteenth": [i * 0.25 for i in range(16)],
        "offbeat": [0.5, 1.5, 2.5, 3.5],
        "none": [],
    },
    "open": {
        "offbeat": [0.5, 1.5, 2.5, 3.5],
        "downbeat": [0],
        "none": [],
    },
    "ride": {
        "eighth": [i * 0.5 for i in range(8)],
        "quarter": [0, 1, 2, 3],
        "none": [],
    },
}

PITCHES = {"kick": KICK, "clap": CLAP, "snare": SNARE, "hat": HAT, "open": OPEN, "ride": RIDE}
VELOCITIES = {"kick": 104, "clap": 96, "snare": 92, "hat": 52, "open": 68, "ride": 58}

# The named kits the older action vocabulary offered, expressed as layers.
KITS: dict[str, dict[str, str]] = {
    "four_floor": {"kick": "four_floor", "clap": "backbeat", "hat": "eighth", "open": "offbeat"},
    "breakbeat": {"kick": "broken", "snare": "backbeat", "hat": "sixteenth"},
    "halftime": {"kick": "halftime", "snare": "third", "hat": "eighth"},
    "minimal": {"kick": "four_floor", "hat": "offbeat"},
    "rolling": {"kick": "rolling", "clap": "backbeat", "hat": "sixteenth", "open": "offbeat"},
    "mainstage": {"kick": "four_floor", "clap": "double", "hat": "sixteenth", "open": "offbeat"},
}


def resolve(kit: str | None, layers: dict[str, str] | None) -> dict[str, str]:
    """Combine a named kit with explicit layer overrides."""
    resolved = dict(KITS[kit]) if kit else {}
    for layer, pattern in (layers or {}).items():
        if layer not in LAYERS:
            raise KeyError(layer)
        if pattern not in LAYERS[layer]:
            raise ValueError(f"{layer} has no pattern called {pattern}")
        resolved[layer] = pattern
    if not resolved:
        resolved = dict(KITS["four_floor"])
    return resolved


def snare_roll(bars: int, start_bar: int) -> list[tuple[float, int]]:
    """An accelerating snare roll: eighths, then sixteenths, then thirty-seconds.

    Used to build tension into a drop. Returns (beat, velocity) pairs measured
    from the start of the pattern.
    """
    hits: list[tuple[float, int]] = []
    remaining = bars - start_bar
    if remaining <= 0:
        return hits
    # Split the remaining bars into three thirds, each twice as fast as the last.
    boundaries = [start_bar, start_bar + remaining / 3, start_bar + 2 * remaining / 3, bars]
    for step, (low, high) in zip((0.5, 0.25, 0.125), zip(boundaries, boundaries[1:])):
        beat = low * 4
        while beat < high * 4 - 1e-9:
            progress = (beat / 4 - start_bar) / max(remaining, 1e-9)
            hits.append((round(beat, 4), int(58 + 62 * min(1.0, progress))))
            beat += step
    return hits


def build(bars: int, kit: str | None = None, layers: dict[str, str] | None = None, *, density: float = 0.7, seed: int = 0, crash: bool = False, fill: bool = False) -> list[Note]:
    """Render a kit into notes for a section of the given length.

    density thins or thickens the busiest layers and controls ghost notes;
    it never removes the kick, which is the part a producer counts on.
    """
    if not 0 <= density <= 1:
        raise ValueError("Density must be between zero and one")
    chosen = resolve(kit, layers)
    rng = random.Random(f"kit:{seed}:{sorted(chosen.items())}")
    notes: list[Note] = []
    end = bars * 4

    def add(pitch: int, start: float, velocity: int, duration: float = 0.11):
        if 0 <= start < end:
            notes.append(Note(pitch=pitch, start=round(start, 4), duration=min(duration, end - start), velocity=max(1, min(127, velocity))))

    for bar in range(bars):
        offset = bar * 4
        last_bar = bar == bars - 1
        for layer, pattern in chosen.items():
            pitch, base = PITCHES[layer], VELOCITIES[layer]
            for index, beat in enumerate(LAYERS[layer][pattern]):
                # Thin the busy layers when density is low; keep the pulse.
                if layer in {"hat", "ride"} and density < 0.5 and index % 2:
                    continue
                velocity = base
                if layer in {"hat", "ride"}:
                    velocity = base + (14 if abs(beat % 1) < 1e-9 else 0) + rng.randint(-5, 5)
                elif layer == "clap" and pattern == "double" and index % 2:
                    velocity = base - 22  # the second hit of the flam sits back
                add(pitch, offset + beat, velocity, 0.16 if layer == "open" else 0.11)
        if crash and bar == 0:
            add(CRASH, offset, 108, 1.0)
        if fill and last_bar:
            for step, pitch in enumerate((HIGH_TOM, HIGH_TOM, MID_TOM, LOW_TOM)):
                add(pitch, offset + 3 + step * 0.25, 88 + step * 4, 0.2)
        elif density > 0.75 and last_bar and chosen.get("kick", "none") != "none":
            add(KICK, offset + 3.75, 74)  # a small pickup into the next bar
    return sorted(notes, key=lambda n: (n.start, n.pitch))


def build_roll(bars: int, start_bar: int, *, pitch: int = SNARE) -> list[Note]:
    """A standalone accelerating roll, for the last bars of a buildup."""
    end = bars * 4
    return [Note(pitch=pitch, start=beat, duration=min(0.1, end - beat), velocity=velocity) for beat, velocity in snare_roll(bars, start_bar) if beat < end]
