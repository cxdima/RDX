"""Production moves: the multi-track gestures producers name in one word.

A move is a macro, not a special case. It expands into ordinary primitive
actions which then go through the same validation as anything else, so the
user can see exactly what "buildup" turned into and undo it as one step.

Defaults are trance/mainstage. Every move takes parameters so it bends to
other music without RDX guessing.
"""
from __future__ import annotations

from ..domain import Action, Project, Section, Track

MELODIC = {"bass", "chords", "lead", "pad"}


def section_of(project: Project, section_id: str) -> Section:
    found = next((s for s in project.sections if s.id == section_id), None)
    if not found:
        raise ValueError("Choose a section for this move")
    return found


def editable(project: Project, roles: set[str] | None = None) -> list[Track]:
    return [t for t in project.tracks if not t.locked and (roles is None or t.role in roles)]


def curve(start: float, end: float, low: float, high: float, steps: int = 8, shape: float = 2.0) -> list[list[float]]:
    """A rising curve as automation points, bent so most of the movement is late."""
    points = []
    for index in range(steps + 1):
        progress = index / steps
        beat = round(start + (end - start) * progress, 4)
        value = round(low + (high - low) * progress**shape, 4)
        points.append([beat, value])
    return points


def buildup(project: Project, section_id: str, *, intensity: float = 0.8, roll: bool = True, riser: bool = True, cut_bars: float = 0.0, from_cutoff: float = 500.0, to_cutoff: float = 15000.0) -> list[Action]:
    """Tension across a section: filter opening, swelling, a roll and a riser.

    cut_bars silences everything for the last stretch, which is the "and then
    it all suddenly drops away" moment before a drop.
    """
    section = section_of(project, section_id)
    length = section.bars * 4
    if not 0 <= cut_bars * 4 < length:
        raise ValueError("The silent tail must be shorter than the section")
    cut_at = length - cut_bars * 4
    actions: list[Action] = [Action(kind="arrange", section=section_id, params={"operation": "update", "energy": round(min(1.0, 0.35 + 0.6 * intensity), 3)})]
    for track in editable(project, MELODIC):
        top = from_cutoff + (to_cutoff - from_cutoff) * intensity
        actions.append(Action(kind="automation", track=track.id, section=section_id, params={"parameter": "cutoff", "points": curve(0, cut_at, from_cutoff, top)}))
        actions.append(Action(kind="automation", track=track.id, section=section_id, params={"parameter": "resonance", "points": [[0, 1.0], [round(cut_at, 4), round(1 + 4 * intensity, 3)]]}))
    if roll:
        drums = editable(project, {"drums"})
        if drums:
            start_bar = max(0, section.bars - max(2, round(section.bars / 2)))
            actions.append(Action(kind="kit", track=drums[0].id, section=section_id, params={"roll": True, "roll_from_bar": start_bar}))
    if riser:
        existing = next((t for t in project.tracks if t.name.lower() == "riser"), None)
        if existing is None:
            actions.append(Action(kind="add_track", params={"role": "pad", "name": "Riser", "preset": "noise"}))
        elif existing.locked:
            raise ValueError("The Riser track is protected; unlock it or turn the riser off")
        actions.append(Action(kind="notes", track="Riser", section=section_id, params={"operation": "replace", "notes": [{"pitch": 60, "start": 0, "duration": round(max(cut_at, 0.25), 4), "velocity": 70}]}))
        actions.append(Action(kind="automation", track="Riser", section=section_id, params={"parameter": "cutoff", "points": curve(0, cut_at, 300, 16000)}))
        actions.append(Action(kind="automation", track="Riser", section=section_id, params={"parameter": "volume_db", "points": curve(0, cut_at, -46, -14, shape=1.6)}))
    if cut_bars > 0:
        actions += fade(project, section_id, start_beat=cut_at, beats=0.5, to_db=-60, include_new=["Riser"])
    return actions


def fade(project: Project, section_id: str, *, start_beat: float = 0.0, beats: float = 4.0, to_db: float = -60.0, include_new: list[str] | None = None) -> list[Action]:
    """Bring everything down together — a quick cut or a slow fall away."""
    section = section_of(project, section_id)
    length = section.bars * 4
    if start_beat < 0 or start_beat >= length:
        raise ValueError("The fade starts outside this section")
    end = min(start_beat + beats, length)
    if end <= start_beat:
        raise ValueError("The fade needs a length")
    targets: list[tuple[str, float]] = [(t.id, t.volume_db) for t in editable(project)]
    targets += [(name, -14.0) for name in include_new or []]
    return [
        Action(kind="automation", track=target, section=section_id, params={"parameter": "volume_db", "points": [[round(start_beat, 4), round(volume, 2)], [round(end, 4), to_db]]})
        for target, volume in targets
    ]


def drop(project: Project, section_id: str, *, intensity: float = 1.0) -> list[Action]:
    """The release after a buildup: full kit, everything open and loud."""
    section_of(project, section_id)
    actions: list[Action] = [Action(kind="arrange", section=section_id, params={"operation": "update", "energy": 1.0})]
    for track in editable(project, MELODIC):
        actions.append(Action(kind="automation", track=track.id, section=section_id, params={"parameter": "cutoff", "operation": "remove"}))
        actions.append(Action(kind="automation", track=track.id, section=section_id, params={"parameter": "volume_db", "operation": "remove"}))
    drums = editable(project, {"drums"})
    if drums:
        actions.append(Action(kind="kit", track=drums[0].id, section=section_id, params={"kit": "mainstage", "density": round(min(1.0, 0.75 + 0.25 * intensity), 3), "crash": True}))
    return actions


def breakdown(project: Project, section_id: str, *, keep: list[str] | None = None) -> list[Action]:
    """Strip back to atmosphere: drums and bass out, space in."""
    section_of(project, section_id)
    kept = {name.lower() for name in keep or ["pad", "chords"]}
    actions: list[Action] = [Action(kind="arrange", section=section_id, params={"operation": "update", "energy": 0.25})]
    for track in editable(project):
        stays = track.role in kept or track.name.lower() in kept
        if stays:
            actions.append(Action(kind="character", track=track.id, params={"character": "dreamy", "intensity": 0.6}))
        else:
            actions.append(Action(kind="automation", track=track.id, section=section_id, params={"parameter": "volume_db", "points": [[0, -60], [max(section_of(project, section_id).bars * 4 - 0.01, 0.01), -60]]}))
    return actions


def layer(project: Project, track_target: str, *, preset: str = "supersaw", layer_name: str | None = None, octave: int = 0, character: str | None = None) -> list[Action]:
    """Double a part onto a new track so two sounds play the same music."""
    source = next((t for t in project.tracks if t.id == track_target or t.name.lower() == str(track_target).lower() or t.role == track_target), None)
    if source is None:
        raise ValueError("Choose one specific track to layer")
    if source.role not in MELODIC:
        raise ValueError("Only instrument parts can be layered")
    layer_name = layer_name or f"{source.name} layer"
    actions = [
        Action(kind="duplicate_track", track=source.id, params={"name": layer_name}),
        Action(kind="sound", track=layer_name, params={"preset": preset}),
    ]
    if octave:
        actions.append(Action(kind="transpose", track=layer_name, section="all", params={"semitones": 12 * octave}))
    if character:
        actions.append(Action(kind="character", track=layer_name, params={"character": character}))
    return actions


MOVES = {"buildup": buildup, "drop": drop, "breakdown": breakdown, "fade": fade, "layer": layer}

DESCRIPTIONS = {
    "buildup": "opens the filters across the section, swells the level, rolls the snare and sweeps a riser in",
    "drop": "clears the buildup automation, puts the full kit back in with a crash and opens everything up",
    "breakdown": "takes the drums and bass out and leaves the harmony in a lot of space",
    "fade": "brings every track down together over the length you choose",
    "layer": "copies a part onto a new track with a different sound so the two play together",
}
