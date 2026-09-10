from __future__ import annotations

import random
import math

from music21 import pitch, scale

from .domain import Action, Automation, Clip, Master, Note, Project, Section, Sound, Track, new_track, uid


class EditError(ValueError):
    pass


def keys(params: dict, allowed: set[str]):
    unknown = set(params) - allowed
    if unknown:
        raise EditError(f"Unsupported settings: {', '.join(sorted(unknown))}")


def parameter_types(params: dict):
    numeric = {"tempo", "seed", "density", "variation", "semitones", "start", "end", "grid", "swing", "humanize", "velocity", "cutoff", "resonance", "attack", "release", "reverb", "delay", "drive", "low", "mid", "high", "volume_db", "delta_db", "pan", "bars", "energy", "index", "ceiling", "compression", "audio_offset"}
    for key, value in params.items():
        if key in numeric and (type(value) not in {int, float} or not math.isfinite(value)):
            raise EditError(f"{key} must be a finite number")
        if key in {"locked", "last_note", "mute", "solo"} and type(value) is not bool:
            raise EditError(f"{key} must be true or false")
        if key in {"name", "role", "key", "scale", "pattern", "preset", "operation", "parameter", "note_id"} and not isinstance(value, str):
            raise EditError(f"{key} must be text")
    if "notes" in params and (not isinstance(params["notes"], list) or any(not isinstance(n, dict) for n in params["notes"])):
        raise EditError("Notes must be a list of note objects")


def target_tracks(project: Project, target: str | None) -> list[Track]:
    if target == "all":
        return [t for t in project.tracks if not t.locked]
    found = [t for t in project.tracks if t.id == target or t.name.lower() == str(target).lower()]
    if not found:
        found = [t for t in project.tracks if t.role == target]
    if len(found) != 1:
        raise EditError("Select one specific track for this change")
    return found


def target_sections(project: Project, target: str | None) -> list[Section]:
    if target == "all":
        return project.sections
    found = [s for s in project.sections if s.id == target or s.name.lower() == str(target).lower()]
    if len(found) != 1:
        raise EditError("Select one specific section for this change")
    return found


def generate_notes(project: Project, track: Track, section: Section, *, density: float = 0.6, variation: int = 0, pattern: str = "four_floor") -> list[Note]:
    if not 0 <= density <= 1:
        raise EditError("Density must be between zero and one")
    if type(variation) is not int:
        raise EditError("Variation must be an integer")
    rng = random.Random(f"{project.seed}:{track.role}:{variation}")
    musical_scale = (scale.MinorScale if project.scale == "minor" else scale.MajorScale)(project.key)
    pcs = [p.pitchClass for p in musical_scale.getPitches(f"{project.key}3", f"{project.key}4")][:7]
    root = pitch.Pitch(project.key).pitchClass
    notes = []

    def add(midi, start, duration, velocity=85):
        notes.append(Note(pitch=int(midi), start=start, duration=duration, velocity=max(1, min(127, velocity))))

    motif = [rng.choice([0, 2, 4, 6, 7, 9]) for _ in range(8)]
    for bar in range(section.bars):
        offset = bar * 4
        degree = ([0, 5, 2, 6] if variation == 0 else [[0, 3, 5, 4], [0, 5, 3, 6], [0, 2, 5, 6]][variation % 3])[(bar // 2) % 4]
        chord_pc = pcs[degree % 7]
        if track.role == "drums":
            if pattern not in {"four_floor", "breakbeat", "halftime", "minimal"}:
                raise EditError("Unknown drum pattern")
            kicks = [0, 1, 2, 3] if pattern == "four_floor" else ([0, 1.75, 2.5] if pattern == "breakbeat" else [0, 2.5])
            for beat in kicks:
                add(36, offset + beat, 0.12, 102 if not variation else rng.randint(91, 108))
            if variation and bar % 2 == 1 and pattern != "minimal":
                add(36, offset + rng.choice([2.75, 3.25, 3.75]), 0.12, 78)
            for beat in ([2] if pattern == "halftime" else [1, 3]):
                add(38, offset + beat, 0.12, 84)
            if pattern != "minimal":
                for step in range(8 if density < 0.8 else 16):
                    beat = step * (0.5 if density < 0.8 else 0.25)
                    add(42 if step % 4 != (3 + variation) % 4 else 46, offset + beat, 0.10, 46 + (step % 2) * 18)
            if density > 0.7 and bar == section.bars - 1:
                for beat in [3.25, 3.5, 3.75]:
                    add(38, offset + beat, 0.1, 60 + int(beat * 5))
        elif track.role == "bass":
            for beat in (([[0, 1.5, 2, 3.5], [0, 0.75, 2, 3], [0, 1, 2.5, 3.5]][variation % 3]) if density > 0.4 else [0, 2]):
                add(36 + chord_pc, offset + beat, 0.42 if density > 0.4 else 1.4, 90)
        elif track.role in {"chords", "pad"}:
            for degree_offset in [0, 2, 4]:
                d = degree + degree_offset
                midi = 48 + pcs[d % 7] + (12 if d >= 7 else 0)
                midi += 12 if degree_offset < (variation % 3) * 2 else 0
                add(midi, offset, 3.8, 60 if track.role == "pad" else 74)
        elif track.role == "lead":
            for step in range(8):
                if rng.random() > density + 0.18:
                    continue
                d = motif[step] + (2 if bar % 4 == 3 and step > 5 else 0)
                midi = 60 + pcs[d % 7] + (12 if d >= 7 else 0)
                add(midi, offset + step * 0.5, 0.24 if step % 3 else 0.45, rng.randint(70, 102))
    return notes


def starter_project() -> Project:
    project = Project(sections=[Section(name="Intro", bars=4, energy=0.35), Section(name="Build", bars=4, energy=0.65), Section(name="Main", bars=8, energy=1), Section(name="Outro", bars=4, energy=0.35)])
    project.tracks = [new_track(role) for role in ("drums", "bass", "chords", "lead")]
    for track in project.tracks:
        for section in project.sections:
            if section.name == "Intro" and track.role in {"bass", "lead"}:
                continue
            if section.name == "Outro" and track.role == "lead":
                continue
            track.clips.append(Clip(name=track.name, section_id=section.id, notes=generate_notes(project, track, section, density=section.energy * 0.75)))
    return Project.model_validate(project.model_dump())


def apply_actions(original: Project, actions: list[Action]) -> Project:
    project = original.model_copy(deep=True)
    originally_locked = {t.id for t in original.tracks if t.locked}
    for action in actions:
        p = action.params
        parameter_types(p)
        if action.kind == "project":
            keys(p, {"name", "tempo", "key", "scale", "seed"})
            updated = Project.model_validate({**project.model_dump(), **p})
            if updated.key != project.key or updated.scale != project.scale:
                old_root, new_root = pitch.Pitch(project.key).pitchClass, pitch.Pitch(updated.key).pitchClass
                shift = (new_root - old_root + 6) % 12 - 6
                old_intervals = [0, 2, 3, 5, 7, 8, 10] if project.scale == "minor" else [0, 2, 4, 5, 7, 9, 11]
                new_intervals = [0, 2, 3, 5, 7, 8, 10] if updated.scale == "minor" else [0, 2, 4, 5, 7, 9, 11]
                for track in updated.tracks:
                    if track.role in {"drums", "audio"}:
                        continue
                    if (track.locked or track.id in originally_locked) and any(c.notes for c in track.clips):
                        raise EditError("Changing key would change a protected track")
                    for clip in track.clips:
                        for note in clip.notes:
                            interval = (note.pitch - old_root) % 12
                            scale_shift = new_intervals[old_intervals.index(interval)] - interval if interval in old_intervals else 0
                            note.pitch += shift + scale_shift
            project = Project.model_validate(updated.model_dump())
            continue
        if action.kind == "master":
            keys(p, set(Master.model_fields))
            project.master = Master.model_validate({**project.master.model_dump(), **p})
            continue
        if action.kind == "add_track":
            keys(p, {"role", "name"})
            if p.get("role") not in {"drums", "bass", "chords", "lead", "pad", "audio"}:
                raise EditError("Choose a supported track role")
            project.tracks.append(new_track(p["role"], p.get("name")))
            continue
        if action.kind == "arrange":
            keys(p, {"operation", "name", "bars", "energy", "index"})
            operation = p.get("operation", "add")
            if operation == "add":
                project.sections.append(Section(name=p.get("name", "Section"), bars=p.get("bars", 8), energy=p.get("energy", 0.7)))
                continue
            section = target_sections(project, action.section)
            if len(section) != 1:
                raise EditError("Choose one section")
            section = section[0]
            if any((t.locked or t.id in originally_locked) and any(c.section_id == section.id for c in t.clips) for t in project.tracks):
                raise EditError("This section contains protected material")
            if operation == "duplicate":
                new = section.model_copy(deep=True)
                new.id, new.name = uid(), p.get("name", section.name + " 2")
                project.sections.insert(project.sections.index(section) + 1, new)
                for track in project.tracks:
                    for clip in list(track.clips):
                        if clip.section_id == section.id:
                            copy = clip.model_copy(deep=True)
                            copy.id, copy.section_id = uid(), new.id
                            for note in copy.notes:
                                note.id = uid()
                            track.clips.append(copy)
                    for lane in list(track.automation):
                        if lane.section_id == section.id:
                            track.automation.append(lane.model_copy(update={"section_id": new.id}, deep=True))
            elif operation == "remove":
                if len(project.sections) == 1:
                    raise EditError("Keep at least one section")
                project.sections.remove(section)
                for track in project.tracks:
                    track.clips = [c for c in track.clips if c.section_id != section.id]
                    track.automation = [a for a in track.automation if a.section_id != section.id]
            elif operation == "move":
                index = p.get("index")
                if not isinstance(index, int) or not 0 <= index < len(project.sections):
                    raise EditError("Section position is outside the arrangement")
                project.sections.remove(section)
                project.sections.insert(index, section)
            elif operation == "update":
                if "bars" in p:
                    checked = Section.model_validate({**section.model_dump(), "bars":p["bars"]})
                    length = checked.bars * 4
                    for track in project.tracks:
                        for clip in track.clips:
                            if clip.section_id == section.id:
                                clip.notes = [n for n in clip.notes if n.start < length]
                                for note in clip.notes:
                                    note.duration = min(note.duration, length - note.start)
                        for lane in track.automation:
                            if lane.section_id == section.id and lane.points[-1][0] > length:
                                left = [point for point in lane.points if point[0] < length]
                                if not left:
                                    lane.points = [(0, lane.points[0][1]), (length, lane.points[0][1])]
                                else:
                                    after = next(point for point in lane.points if point[0] >= length)
                                    before = left[-1]
                                    value = before[1] + (after[1] - before[1]) * (length - before[0]) / (after[0] - before[0])
                                    lane.points = left + [(length, value)]
                for key in ("name", "bars", "energy"):
                    if key in p:
                        setattr(section, key, p[key])
            else:
                raise EditError("Unknown arrangement operation")
            continue
        tracks = target_tracks(project, action.track)
        for track in tracks:
            if (track.locked or track.id in originally_locked) and action.kind != "protect":
                raise EditError(f"{track.name} is protected")
            if action.kind == "protect":
                keys(p, {"locked"})
                if type(p.get("locked")) is not bool:
                    raise EditError("Protection must be true or false")
                track.locked = p["locked"]
            elif action.kind == "remove_track":
                keys(p, set())
                if len(project.tracks) == 1:
                    raise EditError("Keep at least one track")
                project.tracks.remove(track)
            elif action.kind == "duplicate_track":
                keys(p, {"name"})
                new = track.model_copy(deep=True)
                new.id, new.name = uid(), p.get("name", track.name + " 2")
                for clip in new.clips:
                    clip.id = uid()
                    for note in clip.notes:
                        note.id = uid()
                project.tracks.append(new)
            elif action.kind == "sound":
                keys(p, set(Sound.model_fields))
                presets = {"pluck":{"attack":0.005,"release":0.18,"cutoff":6000}, "pad":{"attack":0.4,"release":1.8,"cutoff":4500}, "saw":{"attack":0.01,"release":0.4,"cutoff":9000}, "sine":{"attack":0.01,"release":0.35,"cutoff":12000}, "fm":{"attack":0.008,"release":0.5,"cutoff":10000}}
                track.sound = Sound.model_validate({**track.sound.model_dump(), **presets.get(p.get("preset"), {}), **p})
            elif action.kind == "mix":
                keys(p, {"volume_db", "delta_db", "pan", "mute", "solo", "name"})
                changes = dict(p)
                if "delta_db" in changes:
                    changes["volume_db"] = track.volume_db + float(changes.pop("delta_db"))
                checked = Track.model_validate({**track.model_dump(), **changes})
                for key in changes:
                    setattr(track, key, getattr(checked, key))
            else:
                sections = target_sections(project, action.section)
                for section in sections:
                    clip = next((c for c in track.clips if c.section_id == section.id), None)
                    if action.kind in {"compose", "drums"}:
                        keys(p, {"density", "variation", "pattern"})
                        if track.role == "audio":
                            raise EditError("Record or import audio onto audio tracks")
                        if action.kind == "drums" and track.role != "drums":
                            raise EditError("Choose a drum track for a drum pattern")
                        if not clip:
                            clip = Clip(name=track.name, section_id=section.id)
                            track.clips.append(clip)
                        clip.notes = generate_notes(project, track, section, **p)
                    elif action.kind == "automation":
                        keys(p, {"parameter", "points", "operation"})
                        if p.get("operation") == "remove":
                            track.automation = [a for a in track.automation if not (a.section_id == section.id and a.parameter == p.get("parameter"))]
                            continue
                        lane = Automation(section_id=section.id, **{k:v for k,v in p.items() if k != "operation"})
                        track.automation = [a for a in track.automation if not (a.section_id == section.id and a.parameter == lane.parameter)] + [lane]
                    elif action.kind == "notes" and not clip and p.get("operation", "replace") in {"replace", "add"}:
                        keys(p, {"notes", "operation"})
                        if track.role == "audio":
                            raise EditError("Record or import audio onto audio tracks")
                        track.clips.append(Clip(name=track.name, section_id=section.id, notes=[Note.model_validate(n) for n in p.get("notes", [])]))
                    elif not clip:
                        raise EditError(f"{track.name} has no clip in {section.name}")
                    elif action.kind == "transpose":
                        keys(p, {"semitones", "start", "end", "last_note"})
                        delta = p.get("semitones")
                        if type(delta) is not int or not -48 <= delta <= 48:
                            raise EditError("Transpose requires an integer from -48 to 48")
                        targets = [n for n in clip.notes if p.get("start", 0) <= n.start < p.get("end", section.bars * 4)]
                        if p.get("last_note") and targets:
                            targets = [max(targets, key=lambda n: n.start)]
                        for note in targets:
                            note.pitch += delta
                    elif action.kind == "rhythm":
                        keys(p, {"grid", "swing", "humanize", "velocity"})
                        grid = float(p.get("grid", 0.25))
                        swing = float(p.get("swing", 0))
                        humanize = float(p.get("humanize", 0))
                        if grid not in {0.125, 0.25, 0.5, 1, 2, 4} or not 0 <= swing <= 0.45 or not 0 <= humanize <= 0.08:
                            raise EditError("Rhythm settings are outside their ranges")
                        rng = random.Random(project.seed)
                        for note in clip.notes:
                            step = round(note.start / grid)
                            note.start = max(0, min(section.bars * 4 - note.duration, step * grid + (swing * grid if step % 2 else 0) + rng.uniform(-humanize, humanize)))
                            if "velocity" in p:
                                note.velocity = p["velocity"]
                    elif action.kind == "notes":
                        keys(p, {"notes", "operation", "note_id", "audio_offset"})
                        operation = p.get("operation", "replace")
                        if operation == "replace":
                            clip.notes = [Note.model_validate(n) for n in p.get("notes", [])]
                        elif operation == "add":
                            clip.notes.extend(Note.model_validate(n) for n in p.get("notes", []))
                        elif operation == "remove":
                            clip.notes = [n for n in clip.notes if n.id != p.get("note_id")]
                        elif operation == "audio_offset" and clip.audio_id:
                            clip.audio_offset = float(p["audio_offset"])
                        else:
                            raise EditError("Unknown note edit")
                    else:
                        raise EditError("Unsupported edit")
    return Project.model_validate(project.model_dump())


def context(project: Project, track_id: str | None, section_id: str | None) -> dict:
    return {"tempo": project.tempo, "key": project.key, "scale": project.scale,
            "tracks": [{"id": t.id, "name": t.name, "role": t.role, "locked": t.locked, "volume_db": t.volume_db} for t in project.tracks],
            "sections": [{"id": s.id, "name": s.name, "bars": s.bars} for s in project.sections],
            "selected_track": track_id, "selected_section": section_id}
