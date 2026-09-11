"""Say what actually changed.

The language model proposes edits; this module reports them. The text the user
reads is derived from a diff of the project before and after, so RDX cannot
claim to have done something it did not do. If the model's intent and the real
change disagree, this is the one the user sees.
"""
from __future__ import annotations

from ..domain import Project, Sidechain, Track
from .sidechain import depth_db, nearest_shape

FIELDS = {
    "cutoff": ("filter", "Hz", 0),
    "resonance": ("resonance", "", 1),
    "attack": ("attack", "s", 3),
    "decay": ("decay", "s", 3),
    "sustain": ("sustain", "", 2),
    "release": ("release", "s", 2),
    "filter_env": ("filter envelope", "", 2),
    "filter_decay": ("filter decay", "s", 2),
    "unison": ("voices", "", 0),
    "spread": ("detune", "cents", 0),
    "sub": ("sub oscillator", "", 2),
    "octave": ("octave", "", 0),
    "crush": ("bit crush", "", 2),
    "lfo_depth": ("LFO depth", "", 2),
    "lfo_rate": ("LFO rate", "Hz", 2),
    "reverb": ("reverb", "", 2),
    "delay": ("echo", "", 2),
    "drive": ("drive", "", 2),
    "low": ("lows", "dB", 1),
    "mid": ("mids", "dB", 1),
    "high": ("highs", "dB", 1),
    "chorus": ("chorus", "", 2),
    "flanger": ("flanger", "", 2),
    "phaser": ("phaser", "", 2),
    "autopan": ("auto-pan", "", 2),
    "motion_rate": ("motion rate", "Hz", 2),
    "width": ("width", "", 2),
    "glide": ("glide", "s", 3),
}


AUTOMATION_NAMES = {"volume_db": "level", "pan": "pan"}


def lane_name(parameter: str) -> str:
    return AUTOMATION_NAMES.get(parameter) or FIELDS.get(parameter, (parameter, "", 2))[0]


def count(number: int, noun: str) -> str:
    return f"{number} {noun}" + ("" if number == 1 else "s")


def number(value: float, digits: int) -> str:
    return f"{value:.{digits}f}".rstrip("0").rstrip(".") if digits else f"{value:g}"


def change(label: str, before: float, after: float, unit: str, digits: int) -> str:
    arrow = f"{number(before, digits)} to {number(after, digits)}"
    return f"{label} {arrow}{' ' + unit if unit else ''}"


def section_names(project: Project) -> dict[str, str]:
    return {s.id: s.name for s in project.sections}


def possessive(name: str) -> str:
    """Drums' kick, not Drums's kick."""
    return name + ("'" if name.endswith(("s", "S")) else "'s")


def ducking(setting: Sidechain, tracks: dict[str, str]) -> str:
    """'ducking 12 dB under Drums\' kick (pump)' — the real numbers, not a label."""
    shape = nearest_shape(setting.amount, setting.release, setting.curve)
    source = tracks.get(setting.source, "another track")
    return f"ducking {abs(depth_db(setting.amount))} dB under {possessive(source)} {setting.trigger}" + (f" ({shape})" if shape else f", back over {round(setting.release, 2)} beats")


def track_changes(before: Track, after: Track, names: dict[str, str], tracks: dict[str, str] | None = None) -> list[str]:
    parts: list[str] = []
    if before.name != after.name:
        parts.append(f"renamed to {after.name}")
    if before.sound.preset != after.sound.preset:
        parts.append(f"sound {before.sound.preset} to {after.sound.preset}")
    if before.sound.wave != after.sound.wave:
        parts.append(f"wave {before.sound.wave} to {after.sound.wave}")
    if before.sound.lfo_target != after.sound.lfo_target:
        parts.append(f"LFO off" if after.sound.lfo_target == "off" else f"LFO on the {after.sound.lfo_target}")
    for field, (label, unit, digits) in FIELDS.items():
        old, new = getattr(before.sound, field), getattr(after.sound, field)
        if abs(old - new) > 1e-6:
            parts.append(change(label, old, new, unit, digits))
    if abs(before.volume_db - after.volume_db) > 1e-6:
        parts.append(change("level", before.volume_db, after.volume_db, "dB", 1))
    if abs(before.pan - after.pan) > 1e-6:
        parts.append(change("pan", before.pan, after.pan, "", 2))
    for flag, word in (("mute", "muted"), ("solo", "soloed"), ("locked", "protected")):
        old, new = getattr(before, flag), getattr(after, flag)
        if old != new:
            parts.append(word if new else f"no longer {word}")
    if before.sidechain != after.sidechain:
        parts.append(ducking(after.sidechain, tracks or {}) if after.sidechain else "ducking removed")
    old_clips = {c.section_id: c for c in before.clips}
    for clip in after.clips:
        previous = old_clips.get(clip.section_id)
        where = names.get(clip.section_id, "a section")
        if previous is None:
            parts.append(f"new part in {where} ({count(len(clip.notes), 'note')})")
        elif len(previous.notes) != len(clip.notes):
            parts.append(f"{where} {len(previous.notes)} to {len(clip.notes)} notes")
        elif [(n.pitch, n.start, n.duration, n.velocity) for n in previous.notes] != [(n.pitch, n.start, n.duration, n.velocity) for n in clip.notes]:
            parts.append(f"{where} notes changed")
    for clip in before.clips:
        if clip.section_id not in {c.section_id for c in after.clips}:
            parts.append(f"part removed from {names.get(clip.section_id, 'a section')}")
    old_lanes = {(a.parameter, a.section_id) for a in before.automation}
    new_lanes = {(a.parameter, a.section_id) for a in after.automation}
    for parameter, section_id in sorted(new_lanes - old_lanes):
        parts.append(f"{lane_name(parameter)} automation in {names.get(section_id, 'a section')}")
    for parameter, section_id in sorted(old_lanes - new_lanes):
        parts.append(f"{lane_name(parameter)} automation removed from {names.get(section_id, 'a section')}")
    return parts


def describe(before: Project, after: Project) -> str:
    """A plain reading of every difference between two versions of a project."""
    names = section_names(after) | section_names(before)
    lines: list[str] = []
    project_parts = []
    if before.name != after.name:
        project_parts.append(f"renamed to {after.name}")
    if abs(before.tempo - after.tempo) > 1e-6:
        project_parts.append(f"tempo {number(before.tempo, 0)} to {number(after.tempo, 0)} BPM")
    if (before.key, before.scale) != (after.key, after.scale):
        project_parts.append(f"key {before.key} {before.scale} to {after.key} {after.scale}")
    for field in ("volume_db", "ceiling", "compression"):
        old, new = getattr(before.master, field), getattr(after.master, field)
        if abs(old - new) > 1e-6:
            project_parts.append(change(f"master {field.replace('_db', '')}", old, new, "dB", 1))
    if project_parts:
        lines.append("Project: " + ", ".join(project_parts))

    old_sections = {s.id: s for s in before.sections}
    new_sections = {s.id: s for s in after.sections}
    for section in after.sections:
        previous = old_sections.get(section.id)
        if previous is None:
            lines.append(f"Added section {section.name} ({section.bars} bars)")
        elif previous.bars != section.bars:
            lines.append(f"{section.name}: {previous.bars} to {section.bars} bars")
        elif previous.name != section.name:
            lines.append(f"Section {previous.name} renamed to {section.name}")
    for section in before.sections:
        if section.id not in new_sections:
            lines.append(f"Removed section {section.name}")
    if [s.id for s in before.sections] != [s.id for s in after.sections] and set(old_sections) == set(new_sections):
        lines.append("Reordered the arrangement")

    old_tracks = {t.id: t for t in before.tracks}
    track_names = {t.id: t.name for t in before.tracks} | {t.id: t.name for t in after.tracks}
    for track in after.tracks:
        previous = old_tracks.get(track.id)
        if previous is None:
            notes = sum(len(c.notes) for c in track.clips)
            detail = f"{track.role}, {track.sound.preset}" + (f", {count(notes, 'note')}" if notes else "")
            lines.append(f"Added track {track.name} ({detail})")
            continue
        parts = track_changes(previous, track, names, track_names)
        if parts:
            lines.append(f"{track.name}: " + ", ".join(parts))
    for track in before.tracks:
        if track.id not in {t.id for t in after.tracks}:
            lines.append(f"Removed track {track.name}")
    return "\n".join(lines) if lines else "Nothing changed."
