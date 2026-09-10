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

AUTOMATION_RANGES = {"cutoff": (60, 20000), "resonance": (0.1, 15), "volume_db": (-60, 6), "pan": (-1, 1), "reverb": (0, 1), "flanger": (0, 1), "chorus": (0, 1)}


class Sound(Model):
    preset: Literal[PRESETS] = "pluck"  # type: ignore[valid-type]
    cutoff: float = Field(default=6000, ge=60, le=20000)
    resonance: float = Field(default=1, ge=0.1, le=15)
    attack: float = Field(default=0.01, ge=0.001, le=4)
    release: float = Field(default=0.3, ge=0.01, le=8)
    reverb: float = Field(default=0.15, ge=0, le=1)
    delay: float = Field(default=0.05, ge=0, le=0.8)
    drive: float = Field(default=0, ge=0, le=0.8)
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
    parameter: Literal["cutoff", "resonance", "volume_db", "pan", "reverb", "flanger", "chorus"]
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
    sidechain: Sidechain | None = None
    clips: list[Clip] = Field(default_factory=list, max_length=64)
    automation: list[Automation] = Field(default_factory=list, max_length=64)


class Master(Model):
    volume_db: float = Field(default=-3, ge=-30, le=0)
    ceiling: float = Field(default=-1, ge=-12, le=0)
    compression: float = Field(default=-18, ge=-60, le=0)


class Project(Model):
    id: str = Field(default_factory=uid)
    name: str = Field(default="Untitled 01", min_length=1, max_length=100)
    revision: int = 0
    tempo: float = Field(default=124, ge=40, le=240)
    key: Literal["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"] = "A"
    scale: Literal["minor", "major"] = "minor"
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
    kind: Literal["project", "compose", "drums", "kit", "transpose", "rhythm", "sound", "character", "harmony", "move", "mix", "arrange", "master", "notes", "add_track", "remove_track", "duplicate_track", "protect", "automation", "sidechain", "mix_fix", "phrase"]
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
    sound = Sound(preset=presets[role])
    if role in ("pad", "chords"):
        sound.attack, sound.release, sound.reverb = 0.3, 1.5, 0.25
    if role == "bass":
        sound.cutoff, sound.reverb, sound.delay = 900, 0, 0
    return Track(name=name or role.title(), role=role, color=COLORS[role], sound=sound)
