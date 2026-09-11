from __future__ import annotations

from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


def uid() -> str:
    return uuid4().hex[:12]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Note(Model):
    id: str = Field(default_factory=uid)
    pitch: int = Field(ge=0, le=127)
    start: float = Field(ge=0, le=4096)
    duration: float = Field(gt=0, le=512)
    velocity: int = Field(default=90, ge=1, le=127)


class Clip(Model):
    id: str = Field(default_factory=uid)
    name: str = Field(default="Phrase", max_length=100)
    section_id: str
    notes: list[Note] = Field(default_factory=list, max_length=8192)
    audio_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{12}$")
    audio_offset: float = Field(default=0, ge=0, le=3600)


class Section(Model):
    id: str = Field(default_factory=uid)
    name: str = Field(max_length=60)
    bars: int = Field(default=8, ge=1, le=64)
    energy: float = Field(default=0.7, ge=0, le=1)


# Instrument voices. Melodic tracks may use any of these except the two
# reserved presets; "drumkit" belongs to drum tracks and "audio" to recordings.
PRESETS = ("saw", "supersaw", "pluck", "sine", "sub", "pad", "strings", "choir", "bell", "fm", "noise", "drumkit", "audio")
MELODIC_PRESETS = tuple(p for p in PRESETS if p not in {"drumkit", "audio"})

# General-MIDI drum pitches RDX plays. src/audio/drums.ts mirrors this map and
# tests/test_musical.py asserts the two stay identical.
DRUM_MAP = {36: "Kick", 37: "Rim", 38: "Snare", 39: "Clap", 42: "Hat", 44: "Pedal", 46: "Open", 45: "Low tom", 47: "Mid tom", 50: "High tom", 49: "Crash", 51: "Ride"}

# Parameters a curve can be drawn on. Each one has to be a real signal in the
# audio engine, not just a field on the model: src/audio/engine.ts routes every
# name here to a node, and tests/test_musical.py asserts the two lists match.
AUTOMATION_RANGES = {"cutoff": (60, 20000), "resonance": (0.1, 15), "volume_db": (-60, 6), "pan": (-1, 1), "reverb": (0, 1), "flanger": (0, 1), "chorus": (0, 1), "drive": (0, 0.8), "width": (0, 1), "delay": (0, 0.8), "crush": (0, 1)}
AUTOMATABLE = tuple(AUTOMATION_RANGES)


# The scales RDX writes in, as semitones above the root. Modes are not an
# ornament here: house and techno live in Dorian and Phrygian as much as this
# music lives in natural minor, and a generator that only knows two scales
# cannot write in them however good its rhythm is.
SCALE_STEPS: dict[str, tuple[int, ...]] = {
    "major": (0, 2, 4, 5, 7, 9, 11),
    "minor": (0, 2, 3, 5, 7, 8, 10),
    "dorian": (0, 2, 3, 5, 7, 9, 10),  # minor with a raised sixth
    "phrygian": (0, 1, 3, 5, 7, 8, 10),  # minor with a flattened second
    "lydian": (0, 2, 4, 6, 7, 9, 11),  # major with a raised fourth
    "mixolydian": (0, 2, 4, 5, 7, 9, 10),  # major with a flattened seventh
}
SCALES = tuple(SCALE_STEPS)

PITCH_CLASSES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")

WAVES = ("preset", "saw", "square", "triangle", "sine", "pulse")
LFO_TARGETS = ("off", "cutoff", "pitch", "volume")


class Sound(Model):
    preset: Literal[PRESETS] = "pluck"  # type: ignore[valid-type]
    cutoff: float = Field(default=6000, ge=60, le=20000)
    resonance: float = Field(default=1, ge=0.1, le=15)
    # The amplitude envelope, all four stages. Attack and release alone cannot
    # tell a pluck from a pad: what separates them is how fast the note falls
    # back and how much of it is left holding.
    attack: float = Field(default=0.01, ge=0.001, le=4)
    decay: float = Field(default=0.3, ge=0.005, le=4)
    sustain: float = Field(default=0.6, ge=0, le=1)
    release: float = Field(default=0.3, ge=0.01, le=8)
    # The filter envelope: how far the filter opens on each note and how long
    # it takes to close. This is the control that makes an acid line acid.
    filter_env: float = Field(default=0, ge=-1, le=1)
    filter_decay: float = Field(default=0.3, ge=0.01, le=4)
    # The oscillator itself.
    wave: Literal[WAVES] = "preset"  # type: ignore[valid-type]
    unison: int = Field(default=1, ge=1, le=7)
    spread: float = Field(default=0, ge=0, le=100)  # cents between unison voices
    sub: float = Field(default=0, ge=0, le=1)  # a sine an octave below
    octave: int = Field(default=0, ge=-2, le=2)
    reverb: float = Field(default=0.15, ge=0, le=1)
    delay: float = Field(default=0.05, ge=0, le=0.8)
    drive: float = Field(default=0, ge=0, le=0.8)
    crush: float = Field(default=0, ge=0, le=1)  # bit reduction, 0 is off
    low: float = Field(default=0, ge=-24, le=12)
    mid: float = Field(default=0, ge=-24, le=12)
    high: float = Field(default=0, ge=-24, le=12)
    # Motion: modulation that gives a sound movement rather than tone.
    chorus: float = Field(default=0, ge=0, le=1)
    flanger: float = Field(default=0, ge=0, le=1)
    phaser: float = Field(default=0, ge=0, le=1)
    autopan: float = Field(default=0, ge=0, le=1)
    motion_rate: float = Field(default=0.4, ge=0.02, le=8)
    width: float = Field(default=0, ge=0, le=1)
    glide: float = Field(default=0, ge=0, le=0.5)
    # A dedicated LFO with a named destination, separate from the motion
    # section's shared rate: wobble, vibrato and tremolo are one control each.
    lfo_target: Literal[LFO_TARGETS] = "off"  # type: ignore[valid-type]
    lfo_depth: float = Field(default=0, ge=0, le=1)
    lfo_rate: float = Field(default=4, ge=0.05, le=20)


# Musical starting points for each instrument, applied when a track is created
# and when the preset changes. Explicit parameters in the same action still win.
#
# These are what makes a preset a starting character rather than a waveform
# name: a pluck is a pluck because it decays to almost nothing in a fifth of a
# second, not because of its oscillator.
PRESET_DEFAULTS: dict[str, dict[str, float | int | str]] = {
    "pluck": {"attack": 0.005, "decay": 0.18, "sustain": 0.12, "release": 0.18, "cutoff": 6000},
    "saw": {"attack": 0.01, "decay": 0.3, "sustain": 0.6, "release": 0.4, "cutoff": 9000},
    "supersaw": {"attack": 0.02, "decay": 0.3, "sustain": 0.6, "release": 0.5, "cutoff": 11000, "chorus": 0.25, "width": 0.5, "unison": 7, "spread": 40},
    "sine": {"attack": 0.01, "decay": 0.3, "sustain": 0.6, "release": 0.35, "cutoff": 12000},
    "sub": {"attack": 0.005, "decay": 0.3, "sustain": 0.9, "release": 0.25, "cutoff": 400, "reverb": 0, "delay": 0, "width": 0},
    "pad": {"attack": 0.4, "decay": 0.3, "sustain": 0.8, "release": 1.8, "cutoff": 4500, "unison": 3, "spread": 30},
    "strings": {"attack": 0.35, "decay": 0.3, "sustain": 0.85, "release": 1.6, "cutoff": 5200, "chorus": 0.3, "width": 0.35, "reverb": 0.3, "unison": 4, "spread": 22},
    "choir": {"attack": 0.5, "decay": 0.3, "sustain": 0.9, "release": 2.2, "cutoff": 3800, "reverb": 0.4, "width": 0.4, "unison": 5, "spread": 45},
    "bell": {"attack": 0.002, "decay": 0.3, "sustain": 0.0, "release": 1.4, "cutoff": 14000},
    "fm": {"attack": 0.008, "decay": 0.3, "sustain": 0.6, "release": 0.5, "cutoff": 10000},
    "noise": {"attack": 0.5, "decay": 0.1, "sustain": 1.0, "release": 1.0, "cutoff": 2000, "reverb": 0.3},
}


class Kit(Model):
    """How the drum voices themselves sound, as opposed to what they play.

    `drums.py` decides where a kick lands; this decides what that kick is. They
    are separate because they are separate questions — a 909 pattern with an
    808 kick is a real thing to want, and neither choice implies the other.
    """

    kick_tune: float = Field(default=0, ge=-12, le=12)  # semitones
    kick_decay: float = Field(default=0.3, ge=0.05, le=1.5)
    kick_click: float = Field(default=0.035, ge=0.002, le=0.2)  # pitch sweep time
    snare_tone: float = Field(default=1400, ge=200, le=6000)
    snare_decay: float = Field(default=0.13, ge=0.02, le=0.8)
    clap_spread: float = Field(default=1, ge=0.2, le=3)  # how wide the flam is
    hat_tone: float = Field(default=8500, ge=2000, le=16000)
    hat_decay: float = Field(default=0.035, ge=0.005, le=0.3)
    open_decay: float = Field(default=0.32, ge=0.05, le=1.5)


class Sidechain(Model):
    """Ducking keyed off another track's notes. See rdx/musical/sidechain.py.

    `source` is always a resolved track id by the time it is stored, so the
    reference survives a rename. `amount` is depth as a fraction of the level:
    0.75 leaves a quarter of it, which is 12 dB down.
    """

    source: str = Field(min_length=1, max_length=40)
    amount: float = Field(default=0.75, ge=0, le=1)
    attack: float = Field(default=0.02, ge=0, le=1)
    release: float = Field(default=0.95, gt=0, le=8)
    curve: Literal["exponential", "linear", "smooth"] = "exponential"
    trigger: Literal["kick", "snare", "clap", "rim", "hat", "all"] = "kick"


class Automation(Model):
    parameter: Literal[AUTOMATABLE]  # type: ignore[valid-type]
    section_id: str
    points: list[tuple[float, float]] = Field(min_length=2, max_length=64)

    @model_validator(mode="after")
    def valid_points(self):
        low, high = AUTOMATION_RANGES[self.parameter]
        if any(t < 0 or not low <= v <= high for t, v in self.points):
            raise ValueError("Automation point is outside the supported range")
        if any(a[0] >= b[0] for a, b in zip(self.points, self.points[1:])):
            raise ValueError("Automation times must be increasing")
        return self


class Track(Model):
    id: str = Field(default_factory=uid)
    name: str = Field(max_length=60)
    role: Literal["drums", "bass", "chords", "lead", "pad", "audio"]
    color: str = Field(default="#bde66c", pattern=r"^#[a-fA-F0-9]{6}$")
    volume_db: float = Field(default=-12, ge=-60, le=6)
    pan: float = Field(default=0, ge=-1, le=1)
    mute: bool = False
    solo: bool = False
    locked: bool = False
    sound: Sound = Field(default_factory=Sound)
    # Only drum tracks carry one; validated below so it cannot drift elsewhere.
    kit: Kit | None = None
    sidechain: Sidechain | None = None
    clips: list[Clip] = Field(default_factory=list, max_length=64)
    automation: list[Automation] = Field(default_factory=list, max_length=64)


class Master(Model):
    # Positive gain is allowed and is the point: you reach a limiter's ceiling by
    # pushing into it. Capped at 0 this was a master fader that could only ever
    # make a finished record quieter than it already was, and every rendered
    # record measured about -34 LUFS — roughly 20 dB below a normal one.
    #
    # +6 is where a rendered drop lands at -13.9 LUFS with peaks at -1.4 dBFS,
    # nothing clipped and 8.8 dB of crest left. +9 reaches -11.0 LUFS and clips
    # 13,614 samples, which is the line a professional producer draws for mastering:
    # as loud as you can get it without distorting.
    volume_db: float = Field(default=6, ge=-30, le=12)
    ceiling: float = Field(default=-1, ge=-12, le=0)
    compression: float = Field(default=-18, ge=-60, le=0)


class Project(Model):
    id: str = Field(default_factory=uid)
    name: str = Field(default="Untitled 01", min_length=1, max_length=100)
    revision: int = 0
    tempo: float = Field(default=124, ge=40, le=240)
    key: Literal[PITCH_CLASSES] = "A"  # type: ignore[valid-type]
    scale: Literal[SCALES] = "minor"  # type: ignore[valid-type]
    seed: int = 42
    sections: list[Section] = Field(default_factory=list, max_length=16)
    tracks: list[Track] = Field(default_factory=list, max_length=24)
    master: Master = Field(default_factory=Master)

    @model_validator(mode="after")
    def references(self):
        section_ids = {s.id for s in self.sections}
        if len(section_ids) != len(self.sections) or len({t.id for t in self.tracks}) != len(self.tracks):
            raise ValueError("Duplicate project objects")
        if sum(s.bars for s in self.sections) > 256:
            raise ValueError("This version supports arrangements up to 256 bars")
        bars = {s.id: s.bars for s in self.sections}
        track_ids = {t.id for t in self.tracks}
        for track in self.tracks:
            if track.kit and track.role != "drums":
                raise ValueError("Only drum tracks have drum voices")
            if track.role == "drums" and track.kit is None:
                # A project saved before drum voices existed still has drums.
                # Filling the defaults on load means every drum track answers
                # the same questions, however old the file is.
                track.kit = Kit()
            if track.sidechain:
                if track.sidechain.source == track.id:
                    raise ValueError("A track cannot duck to itself")
                if track.sidechain.source not in track_ids:
                    raise ValueError("Ducking refers to a track that is no longer in the project")
            expected = "drumkit" if track.role == "drums" else "audio" if track.role == "audio" else None
            if expected and track.sound.preset != expected or not expected and track.sound.preset in {"drumkit", "audio"}:
                raise ValueError("Instrument preset does not match its track type")
            if len({c.section_id for c in track.clips}) != len(track.clips):
                raise ValueError("One clip per track and section is supported")
            for clip in track.clips:
                if track.role == "audio" and clip.notes or track.role != "audio" and clip.audio_id:
                    raise ValueError("Keep MIDI notes on instrument tracks and recordings on audio tracks")
                if clip.section_id not in section_ids:
                    raise ValueError("Clip refers to a missing section")
                if len({n.id for n in clip.notes}) != len(clip.notes):
                    raise ValueError("Duplicate note IDs")
                if any(n.start + n.duration > bars[clip.section_id] * 4 + 0.001 for n in clip.notes):
                    raise ValueError("A note extends beyond its section")
            for lane in track.automation:
                if lane.section_id not in section_ids or lane.points[-1][0] > bars[lane.section_id] * 4:
                    raise ValueError("Automation extends beyond its section")
            if len({(a.parameter, a.section_id) for a in track.automation}) != len(track.automation):
                raise ValueError("Duplicate automation lanes")
        return self


class Action(Model):
    kind: Literal["project", "compose", "drums", "kit", "transpose", "rhythm", "sound", "character", "harmony", "move", "mix", "arrange", "master", "notes", "add_track", "remove_track", "duplicate_track", "protect", "automation", "sidechain", "mix_fix", "phrase", "relate", "kit_sound", "bassline", "melody", "record"]
    track: str | None = None
    section: str | None = None
    params: dict = Field(default_factory=dict)


class Plan(Model):
    """What the model proposed.

    `summary` is the model's own wording and is kept only for training records:
    what the user sees is generated from the real change. `note` carries a
    question or a plain "I cannot do that" when there are no actions.
    """

    summary: str = Field(default="", max_length=1200)
    note: str = Field(default="", max_length=1200)
    actions: list[Action] = Field(default_factory=list, max_length=24)


class EditRequest(Model):
    revision: int
    actions: list[Action] = Field(min_length=1, max_length=24)
    label: str = Field(default="Edit", max_length=150)


COLORS = {"drums": "#ed987b", "bass": "#bde66c", "chords": "#ac9ae8", "lead": "#76ced8", "pad": "#dfafce", "audio": "#cfba79"}


def new_track(role: str, name: str | None = None) -> Track:
    presets = {"drums": "drumkit", "bass": "sine", "chords": "pad", "lead": "pluck", "pad": "pad", "audio": "audio"}
    preset = presets[role]
    sound = Sound.model_validate({"preset": preset, **PRESET_DEFAULTS.get(preset, {})})
    kit = Kit() if role == "drums" else None
    if role in ("pad", "chords"):
        sound.attack, sound.release, sound.reverb = 0.3, 1.5, 0.25
    if role == "bass":
        sound.cutoff, sound.reverb, sound.delay = 900, 0, 0
    return Track(name=name or role.title(), role=role, color=COLORS[role], sound=sound, kit=kit)
