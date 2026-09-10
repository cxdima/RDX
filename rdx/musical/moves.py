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
    section = section_of(project, section_id)
    silent = [[0, -60], [max(section.bars * 4 - 0.01, 0.01), -60]]
    kept = {name.lower() for name in keep or ["pad", "chords"]}
    actions: list[Action] = [Action(kind="arrange", section=section_id, params={"operation": "update", "energy": 0.25})]
    for track in editable(project):
        stays = track.role in kept or track.name.lower() in kept
        if stays:
            actions.append(Action(kind="character", track=track.id, params={"character": "dreamy", "intensity": 0.6}))
        else:
            actions.append(Action(kind="automation", track=track.id, section=section_id, params={"parameter": "volume_db", "points": list(silent)}))
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


def pump(project: Project, *, shape: str = "pump", source: str | None = None, tracks: list[str] | None = None, amount: float | None = None) -> list[Action]:
    """Duck everything melodic under the kick — the groove of dance music.

    Named tracks win; otherwise every unlocked instrument part gets it, which
    is what "make it pump" means in practice. Drums keep their own transients.
    """
    if tracks:
        wanted = {str(name).lower() for name in tracks}
        targets = [t for t in editable(project) if t.id in wanted or t.name.lower() in wanted or t.role in wanted]
        if not targets:
            raise ValueError("None of those tracks are available to duck")
    else:
        targets = editable(project, MELODIC)
    if not targets:
        raise ValueError("There are no instrument parts to duck")
    settings: dict = {"shape": shape}
    if source:
        settings["source"] = source
    if amount is not None:
        settings["amount"] = amount
    return [Action(kind="sidechain", track=track.id, params=dict(settings)) for track in targets]


def transition(project: Project, section_id: str, *, beats: float = 4.0, crash: bool = True, sweep: bool = True, impact: bool = True) -> list[Action]:
    """The join between two sections: a sweep out, a crash in, a moment of air.

    A transition is the one thing a producer hears immediately when it is
    missing. It is three small gestures at the seam rather than one effect:
    the outgoing section opens up, everything drops for a beat, and the new
    one starts on a crash.
    """
    section = section_of(project, section_id)
    length = section.bars * 4
    if not 0 < beats <= length:
        raise ValueError("The transition has to be shorter than the section it ends")
    start = length - beats
    actions: list[Action] = []
    if sweep:
        for track in editable(project, MELODIC):
            actions.append(Action(kind="automation", track=track.id, section=section_id, params={"parameter": "cutoff", "points": curve(start, length, track.sound.cutoff, 18000, steps=6, shape=1.4)}))
    if impact:
        # The last half beat is silent on everything, which is what makes the
        # next downbeat land. Producers call it the gap and it is mostly air.
        gap = max(start, length - 0.5)
        actions += fade(project, section_id, start_beat=gap, beats=0.25, to_db=-60)
    if crash:
        following = next((s for s in project.sections[project.sections.index(section) + 1 :]), None)
        drums = editable(project, {"drums"})
        if following and drums:
            actions.append(Action(kind="kit", track=drums[0].id, section=following.id, params={"crash": True}))
    if not actions:
        raise ValueError("Choose at least one part of the transition to keep")
    return actions


def riser(project: Project, section_id: str, *, bars: float = 0.0, preset: str = "noise", name: str = "Riser", to_db: float = -12.0) -> list[Action]:
    """A riser as a thing in its own right, not a side effect of a buildup.

    Producers reach for one on its own — over a breakdown, into a bridge — so
    it is its own move, on its own track, reusing the same track if it is there.
    """
    section = section_of(project, section_id)
    length = section.bars * 4
    span = bars * 4 if bars > 0 else length
    if not 0 < span <= length:
        raise ValueError("The riser has to fit inside the section")
    start = length - span
    existing = next((t for t in project.tracks if t.name.lower() == name.lower()), None)
    if existing and existing.locked:
        raise ValueError(f"The {existing.name} track is protected; unlock it first")
    actions: list[Action] = []
    if existing is None:
        actions.append(Action(kind="add_track", params={"role": "pad", "name": name, "preset": preset}))
    actions += [
        Action(kind="notes", track=name, section=section_id, params={"operation": "replace", "notes": [{"pitch": 60, "start": round(start, 4), "duration": round(span, 4), "velocity": 70}]}),
        Action(kind="automation", track=name, section=section_id, params={"parameter": "cutoff", "points": curve(start, length, 300, 16000)}),
        Action(kind="automation", track=name, section=section_id, params={"parameter": "volume_db", "points": curve(start, length, -46, to_db, shape=1.6)}),
    ]
    return actions


def double_time(project: Project, section_id: str, *, factor: float = 2.0, roles: list[str] | None = None) -> list[Action]:
    """Halve or double the note spacing of a section without changing the tempo.

    "Make the drums double time" is a rhythmic instruction, not a tempo one:
    the track stays at 128 and the part plays twice as fast inside it.
    """
    section = section_of(project, section_id)
    if factor not in {0.5, 2.0}:
        raise ValueError("This changes the feel to half time or double time")
    length = section.bars * 4
    wanted = {r.lower() for r in roles} if roles else None
    actions: list[Action] = []
    for track in editable(project):
        if wanted and track.role not in wanted and track.name.lower() not in wanted:
            continue
        clip = next((c for c in track.clips if c.section_id == section_id), None)
        if not clip or not clip.notes:
            continue
        notes = []
        for note in clip.notes:
            start = note.start / factor if factor > 1 else note.start * (1 / factor)
            duration = note.duration / factor if factor > 1 else note.duration * (1 / factor)
            if start >= length - 1e-6:
                continue
            notes.append({"pitch": note.pitch, "start": round(start, 4), "duration": round(min(duration, length - start), 4), "velocity": note.velocity})
        if factor > 1:
            # Twice as fast leaves the back half empty; repeat it so the
            # section is still full, which is what "double time" sounds like.
            repeats = int(factor)
            block = length / repeats
            notes = [{**n, "start": round(n["start"] + copy * block, 4)} for copy in range(repeats) for n in notes if n["start"] + copy * block < length - 1e-6]
        if notes:
            actions.append(Action(kind="notes", track=track.id, section=section_id, params={"operation": "replace", "notes": notes}))
    if not actions:
        raise ValueError("There is nothing in this section to change the feel of")
    return actions


MOVES = {"buildup": buildup, "drop": drop, "breakdown": breakdown, "fade": fade, "layer": layer, "pump": pump, "transition": transition, "riser": riser, "double_time": double_time}

# Moves that change how tracks behave everywhere rather than inside one
# section, so the engine must not hand them a section to work in.
WHOLE_TRACK_MOVES = {"pump"}

DESCRIPTIONS = {
    "buildup": "opens the filters across the section, swells the level, rolls the snare and sweeps a riser in",
    "drop": "clears the buildup automation, puts the full kit back in with a crash and opens everything up",
    "breakdown": "takes the drums and bass out and leaves the harmony in a lot of space",
    "fade": "brings every track down together over the length you choose",
    "layer": "copies a part onto a new track with a different sound so the two play together",
    "pump": "ducks every instrument part under the kick so the track breathes with the beat",
    "transition": "sweeps the filters open at the end of a section, leaves a gap, and starts the next one on a crash",
    "riser": "sweeps a noise riser up into the end of the section on its own track",
    "double_time": "plays the same parts at half or double speed without changing the tempo",
}
