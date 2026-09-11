from __future__ import annotations

import random
import math

from .domain import Action, AUTOMATION_RANGES, Automation, Clip, Kit, Master, MELODIC_PRESETS, Note, PITCH_CLASSES, PRESET_DEFAULTS, SCALE_STEPS, Project, Section, Sidechain, Sound, Track, new_track, uid
from .musical import bass as bass_module
from .musical import character as character_module
from .musical import design as design_module
from .musical import drums as drums_module
from .musical import genres as genres_module
from .musical import harmony as harmony_module
from .musical import melody as melody_module
from .musical import mixdown as mixdown_module
from .musical import motif as motif_module
from .musical import moves as moves_module
from .musical import parts as parts_module
from .musical import sidechain as sidechain_module


class EditError(ValueError):
    pass


class Unsupported(EditError):
    """The request names something RDX genuinely cannot do.

    Separate from a validation failure so the model is never invited to retry
    a request that no amount of rephrasing will satisfy.
    """


def keys(params: dict, allowed: set[str]):
    unknown = set(params) - allowed
    if unknown:
        raise EditError(f"Unsupported settings: {', '.join(sorted(unknown))}")


NUMERIC_PARAMS = {"kick_tune", "kick_decay", "kick_click", "snare_tone", "snare_decay", "clap_spread", "hat_tone", "hat_decay", "open_decay", "factor", "decay", "sustain", "filter_env", "filter_decay", "unison", "spread", "sub", "crush", "lfo_depth", "lfo_rate", "tempo", "seed", "density", "variation", "semitones", "start", "end", "grid", "swing", "humanize", "velocity", "cutoff", "resonance", "attack", "release", "reverb", "delay", "drive", "low", "mid", "high", "volume_db", "delta_db", "pan", "bars", "energy", "index", "ceiling", "compression", "audio_offset", "chorus", "flanger", "phaser", "autopan", "motion_rate", "width", "glide", "intensity", "span", "voices", "roll_from_bar", "octave", "cut_bars", "from_cutoff", "to_cutoff", "start_beat", "beats", "to_db", "amount", "degrees"}
BOOLEAN_PARAMS = {"locked", "last_note", "mute", "solo", "crash", "fill", "roll", "riser", "keep_rhythm", "sweep", "impact", "accelerate", "pickup", "replace"}
TEXT_PARAMS = {"name", "role", "key", "scale", "pattern", "preset", "operation", "parameter", "note_id", "character", "kit", "from_track", "track", "layer_name", "source", "curve", "trigger", "shape", "problem", "colour", "against", "patch", "wave", "lfo_target", "machine", "progression", "structure", "pattern", "genre", "cell", "form", "anchor"}


def parameter_types(params: dict):
    for key, value in params.items():
        if key in NUMERIC_PARAMS and (type(value) not in {int, float} or not math.isfinite(value)):
            raise EditError(f"{key} must be a finite number")
        if key in BOOLEAN_PARAMS and type(value) is not bool:
            raise EditError(f"{key} must be true or false")
        if key in TEXT_PARAMS and not isinstance(value, str):
            raise EditError(f"{key} must be text")
    if "notes" in params and (not isinstance(params["notes"], list) or any(not isinstance(n, dict) for n in params["notes"])):
        raise EditError("Notes must be a list of note objects")


def count_parts(number: int) -> str:
    return f"{number} part" + ("" if number == 1 else "s")


def validated(project: Project) -> Project:
    """Re-check the whole project and translate any failure into plain language."""
    try:
        return Project.model_validate(project.model_dump())
    except EditError:
        raise
    except ValueError as error:
        message = getattr(error, "errors", None)
        if callable(message):
            reasons = [str(e.get("msg", "")).replace("Value error, ", "") for e in error.errors()]
            unique = list(dict.fromkeys(r for r in reasons if r))
            if unique:
                raise EditError("That edit would leave the project inconsistent: " + "; ".join(unique[:3])) from error
        raise EditError("That edit would leave the project inconsistent") from error


# Kinds that name their own target, so the model never has to echo an id back.
ROLE_IMPLIED_BY_KIND = {"drums": "drums", "kit": "drums"}


def resolve_track(project: Project, target: str | None, selection: dict | None, kind: str = "") -> str | None:
    """Fill in an omitted or 'selected' track target.

    Small models are poor at copying a random id out of the context and good
    at naming what they mean, so RDX resolves the target here instead of
    making the model do clerical work it will get wrong.
    """
    if target not in (None, "", "selected"):
        return target
    role = ROLE_IMPLIED_BY_KIND.get(kind)
    if role:
        matching = [t for t in project.tracks if t.role == role]
        if len(matching) == 1:
            return matching[0].id
    if selection and selection.get("track"):
        return selection["track"]
    return target


def resolve_section(project: Project, target: str | None, selection: dict | None) -> str | None:
    if target not in (None, "", "selected"):
        return target
    if selection and selection.get("section"):
        return selection["section"]
    return target


def target_tracks(project: Project, target: str | None, selection: dict | None = None, kind: str = "") -> list[Track]:
    target = resolve_track(project, target, selection, kind)
    if target == "all":
        return [t for t in project.tracks if not t.locked]
    found = [t for t in project.tracks if t.id == target or t.name.lower() == str(target).lower()]
    if not found:
        found = [t for t in project.tracks if t.role == target]
    if len(found) == 1:
        return found
    available = ", ".join(f"{t.name} ({t.role})" for t in project.tracks)
    if not target:
        raise EditError(f"Say which track this is for. The project has: {available}.")
    if not found:
        raise EditError(f"There is no track called '{target}'. The project has: {available}.")
    raise EditError(f"More than one track matches '{target}'. Name one of: {available}.")


def default_source(project: Project, target: str | None, ducked: Track) -> Track:
    """The track whose hits key a duck.

    Almost always the kick, so an unnamed source finds the one drum track
    rather than making the model guess an id. With no drum track and nothing
    named, saying so beats picking something arbitrary.
    """
    if target in (None, "", "selected"):
        drums = [t for t in project.tracks if t.role == "drums" and t.id != ducked.id]
        if len(drums) == 1:
            return drums[0]
        raise EditError("Say which track should trigger the ducking, for example the drums.")
    return target_tracks(project, target)[0]


def target_sections(project: Project, target: str | None, selection: dict | None = None) -> list[Section]:
    target = resolve_section(project, target, selection)
    if target == "all":
        return project.sections
    found = [s for s in project.sections if s.id == target or s.name.lower() == str(target).lower()]
    if len(found) == 1:
        return found
    available = ", ".join(s.name for s in project.sections)
    if not target:
        raise EditError(f"Say which section this is for. The arrangement has: {available}.")
    raise EditError(f"There is no section called '{target}'. The arrangement has: {available}.")


def progression_for(project: Project, params: dict, section: Section, selection: dict | None, purpose: str) -> list[tuple[float, float, object]]:
    """The chords a part should follow: either named outright, or read off the
    harmony track so a bass and a melody written separately still agree."""
    wanted = params.get("progression")
    if wanted:
        try:
            if wanted in harmony_module.NAMED_PROGRESSIONS:
                return harmony_module.named(wanted, section.bars, project.key, project.scale)
            return harmony_module.from_degrees(harmony_module.parse_progression(wanted), section.bars, project.key, project.scale)
        except (KeyError, ValueError) as error:
            raise EditError(str(error)) from error
    source_track = target_tracks(project, params.get("from_track") or "chords", selection)[0]
    source = next((c for c in source_track.clips if c.section_id == section.id), None)
    if source is None or not source.notes:
        raise EditError(f"{source_track.name} has nothing in {section.name} {purpose}. Name a progression instead.")
    return harmony_module.progression(source.notes, section.bars, project.key, project.scale)


def generate_notes(project: Project, track: Track, section: Section, *, density: float = 0.6, variation: int = 0, pattern: str = "four_floor") -> list[Note]:
    if not 0 <= density <= 1:
        raise EditError("Density must be between zero and one")
    if type(variation) is not int:
        raise EditError("Variation must be an integer")
    rng = random.Random(f"{project.seed}:{track.role}:{variation}")
    root = PITCH_CLASSES.index(project.key)
    pcs = [(root + step) % 12 for step in SCALE_STEPS[project.scale]]
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


def apply_actions(original: Project, actions: list[Action], selection: dict | None = None, findings: list[str] | None = None, measured: dict | None = None, _depth: int = 0) -> Project:
    project = original.model_copy(deep=True)
    originally_locked = {t.id for t in original.tracks if t.locked}
    for action in actions:
        p = action.params
        parameter_types(p)
        if action.kind == "mix_fix":
            keys(p, {"problem"})
            if _depth:
                raise EditError("A mix correction cannot be nested inside another edit")
            if not measured:
                # RDX will not guess at a mix problem. This is the one kind of
                # request where the honest answer is "let me listen first".
                raise EditError("Analyse the mix before asking me to fix it — I will not guess at a problem I have not measured. Use Analyse the mix in the mixer.")
            mix = mixdown_module.Mix.from_dict(measured)
            available = mixdown_module.findings(mix, project)
            if not available:
                raise EditError("Nothing in this mix measures as a problem, so there is nothing for me to correct.")
            wanted = p.get("problem")
            chosen = available if wanted in (None, "", "all") else [f for f in available if f.problem == wanted]
            if not chosen:
                names = ", ".join(sorted({f.problem for f in available}))
                raise Unsupported(f"The mix does not measure as '{wanted}'. What it does show: {names}.")
            expanded = [Action.model_validate(a) for f in chosen for a in f.actions]
            if not expanded:
                raise EditError("There is no edit RDX can make for that measurement")
            if findings is not None:
                findings.extend(f"{f.headline}. {f.detail}" for f in chosen)
            project = apply_actions(project, expanded, selection, None, measured, _depth + 1)
            continue
        if action.kind == "record":
            keys(p, {"genre", "bars", "key", "replace"})
            if _depth:
                raise EditError("A record is the whole arrangement; it cannot be nested inside another edit")
            genre = p.get("genre")
            if genre not in genres_module.GENRES:
                raise Unsupported(f"RDX does not know how to make a '{genre}' record. It knows: {', '.join(genres_module.GENRES)}.")
            try:
                setup = genres_module.record(project, genre, bars=p.get("bars"), key=p.get("key"))
            except ValueError as error:
                raise EditError(str(error)) from error
            # A record lays out its own arrangement, so the sections it replaces
            # go. Appending instead is what produced a trance record bolted onto
            # the end of the starter demo: 116 bars, four dead sections at the
            # front and a section called "Build 2 2".
            #
            # This is destructive, and it is allowed to be because it is neither
            # silent nor irreversible: the whole record is one atomic edit that
            # the user sees as a preview and accepts, the removals are ordinary
            # actions in the history, and `replace: false` appends instead — for
            # putting a second record in a project that already holds one.
            replacing = list(project.sections) if p.get("replace", True) else [s for s in project.sections if not any(c.section_id == s.id and c.notes for tr in project.tracks for c in tr.clips)]
            clearing: list[Action] = []
            if replacing:
                # One has to survive until the new sections exist, and it is
                # renamed so it cannot collide with the names coming in.
                clearing = [Action(kind="arrange", section=s.id, params={"operation": "remove"}) for s in replacing[1:]]
                clearing.append(Action(kind="arrange", section=replacing[0].id, params={"operation": "update", "name": "Replaced"}))
                project = apply_actions(project, clearing, selection, None, measured, 0)
            # Two passes: the structure has to exist before its sections can be
            # filled, and the parts have to exist before a move can shape them.
            before = {s.name for s in project.sections}
            project = apply_actions(project, setup, selection, None, measured, 0)
            if replacing:
                leftover = next((s for s in project.sections if s.name == "Replaced"), None)
                if leftover and len(project.sections) > 1:
                    project = apply_actions(project, [Action(kind="arrange", section=leftover.id, params={"operation": "remove"})], selection, None, measured, 0)
            fresh = [s.name for s in project.sections if s.name not in before]
            project = apply_actions(project, genres_module.parts_for(project, genre, fresh), selection, None, measured, 0)
            project = apply_actions(project, genres_module.shape_for(project, genre, fresh), selection, None, measured, 0)
            if findings is not None:
                findings.append(f"Built a {genres_module.describe(genre)}")
                findings.append(f"Sections: {', '.join(fresh)}.")
                findings.append(f"Bass: {bass_module.describe(genres_module.GENRES[genre].bass)}.")
            continue
        if action.kind == "move":
            keys(p, {"name", "intensity", "roll", "riser", "cut_bars", "from_cutoff", "to_cutoff", "track", "preset", "layer_name", "octave", "character", "keep", "start_beat", "beats", "to_db", "shape", "source", "tracks", "amount", "crash", "sweep", "impact", "bars", "factor", "roles", "grid", "accelerate", "structure", "kit", "layers", "pickup"})
            if _depth:
                raise EditError("A production move cannot contain another move")
            name = p.get("name")
            if name not in moves_module.MOVES:
                raise Unsupported(f"'{name}' is not a production move RDX knows. Available: {', '.join(sorted(moves_module.MOVES))}.")
            arguments = {k: v for k, v in p.items() if k != "name"}
            if name == "layer":
                arguments["track_target"] = resolve_track(project, arguments.pop("track", None) or action.track, selection, "layer")
            elif name in moves_module.WHOLE_TRACK_MOVES:
                arguments.pop("track", None)
            else:
                arguments["section_id"] = target_sections(project, action.section, selection)[0].id
            try:
                expanded = moves_module.MOVES[name](project, **arguments)
            except TypeError as error:
                raise EditError(f"The {name} move does not take those settings") from error
            except EditError:
                raise
            except ValueError as error:
                raise EditError(str(error)) from error
            project = apply_actions(project, expanded, selection, findings, measured, _depth + 1)
            continue
        if action.kind == "project":
            keys(p, {"name", "tempo", "key", "scale", "seed"})
            try:
                updated = Project.model_validate({**project.model_dump(), **p})
            except ValueError as error:
                raise EditError(f"Those project settings are out of range: {', '.join(sorted(p))}") from error
            if updated.key != project.key or updated.scale != project.scale:
                old_root, new_root = PITCH_CLASSES.index(project.key), PITCH_CLASSES.index(updated.key)
                shift = (new_root - old_root + 6) % 12 - 6
                # Moving between modes keeps each note on its own scale degree,
                # so a melody stays the same melody and only its colour changes.
                old_intervals = list(SCALE_STEPS[project.scale])
                new_intervals = list(SCALE_STEPS[updated.scale])
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
            project = validated(updated)
            continue
        if action.kind == "master":
            keys(p, set(Master.model_fields))
            project.master = Master.model_validate({**project.master.model_dump(), **p})
            continue
        if action.kind == "add_track":
            keys(p, {"role", "name", "preset"})
            if p.get("role") not in {"drums", "bass", "chords", "lead", "pad", "audio"}:
                raise EditError("Choose a supported track role")
            track = new_track(p["role"], p.get("name"))
            if "preset" in p:
                if p["preset"] not in MELODIC_PRESETS:
                    raise Unsupported(f"There is no '{p['preset']}' instrument. Available: {', '.join(MELODIC_PRESETS)}.")
                if p["role"] in {"drums", "audio"}:
                    raise EditError("Drum and audio tracks do not take an instrument preset")
                track.sound.preset = p["preset"]
            project.tracks.append(track)
            continue
        if action.kind == "arrange":
            keys(p, {"operation", "name", "bars", "energy", "index", "from_section", "tracks"})
            operation = p.get("operation", "add")
            if operation == "add":
                project.sections.append(Section(name=p.get("name", "Section"), bars=p.get("bars", 8), energy=p.get("energy", 0.7)))
                continue
            section = target_sections(project, action.section, selection)
            if len(section) != 1:
                raise EditError("Choose one section")
            section = section[0]
            # Only operations that would move, copy or shorten protected notes
            # are blocked. Renaming a section or changing its energy is safe.
            disturbs_material = operation in {"duplicate", "remove", "move", "copy"} or (operation == "update" and "bars" in p)
            if disturbs_material and any((t.locked or t.id in originally_locked) and any(c.section_id == section.id for c in t.clips) for t in project.tracks):
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
            elif operation == "copy":
                # "Make the second drop like the first." Duplicating a section
                # makes a new one; this fills a section that already exists,
                # which is how an arrangement gets its repeats.
                sources = target_sections(project, p.get("from_section"), selection)
                if len(sources) != 1:
                    raise EditError("Say which one section to copy from")
                source = sources[0]
                if source.id == section.id:
                    raise EditError(f"{section.name} is already itself; name the section to copy from")
                wanted = {str(name).lower() for name in p.get("tracks") or []}
                length = section.bars * 4
                copied = 0
                for track in project.tracks:
                    if wanted and track.id not in wanted and track.name.lower() not in wanted and track.role not in wanted:
                        continue
                    if track.locked or track.id in originally_locked:
                        continue
                    original_clip = next((c for c in track.clips if c.section_id == source.id), None)
                    track.clips = [c for c in track.clips if c.section_id != section.id]
                    track.automation = [a for a in track.automation if a.section_id != section.id]
                    if original_clip is None:
                        continue
                    copy = original_clip.model_copy(deep=True)
                    copy.id, copy.section_id = uid(), section.id
                    # A shorter destination keeps what fits rather than failing.
                    copy.notes = [n for n in copy.notes if n.start < length]
                    for note in copy.notes:
                        note.id, note.duration = uid(), min(note.duration, length - note.start)
                    track.clips.append(copy)
                    for lane in [a for a in track.automation if a.section_id == source.id]:
                        moved = lane.model_copy(update={"section_id": section.id}, deep=True)
                        points = [(round(min(beat, length), 4), value) for beat, value in moved.points]
                        deduped = [point for index, point in enumerate(points) if index == 0 or point[0] > points[index - 1][0]]
                        if len(deduped) >= 2:
                            track.automation.append(moved.model_copy(update={"points": deduped}))
                    copied += 1
                if not copied:
                    raise EditError(f"There is nothing in {source.name} to copy into {section.name}")
                if findings is not None:
                    findings.append(f"Copied {count_parts(copied)} from {source.name} into {section.name}.")
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
        tracks = target_tracks(project, action.track, selection, action.kind)
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
                # Anything ducking to it loses its trigger rather than leaving
                # a reference the project can no longer validate.
                for other in project.tracks:
                    if other.sidechain and other.sidechain.source == track.id:
                        other.sidechain = None
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
                keys(p, set(Sound.model_fields) | {"patch"})
                patch: dict = {}
                if "patch" in p:
                    name = p["patch"]
                    if name not in design_module.PATCHES:
                        raise Unsupported(f"There is no '{name}' sound. RDX knows: {', '.join(sorted(design_module.PATCHES))}.")
                    if track.role in {"drums", "audio"}:
                        raise EditError(f"{track.name} is a {track.role} track; patches are for instrument parts")
                    if not design_module.suits(name, track.role):
                        where = " or ".join(design_module.PATCHES[name].roles)
                        raise EditError(f"A {name.replace('_', ' ')} belongs on {where}, and {track.name} is the {track.role}. Put it on a {where} track or say which sound you want there instead.")
                    patch = design_module.patch_settings(name)
                    if findings is not None:
                        findings.append(f"{track.name}: {design_module.describe_patch(name)}.")
                p = {k: v for k, v in p.items() if k != "patch"}
                if "preset" in p:
                    if p["preset"] not in MELODIC_PRESETS:
                        raise Unsupported(f"There is no '{p['preset']}' instrument. Available: {', '.join(MELODIC_PRESETS)}.")
                    if track.role in {"drums", "audio"}:
                        raise EditError(f"{track.name} is a {track.role} track and does not take an instrument preset")
                try:
                    # A patch is a whole sound, so it replaces rather than
                    # blends; anything named alongside it still wins.
                    base = Sound().model_dump() if patch else track.sound.model_dump()
                    preset_start = PRESET_DEFAULTS.get(patch.get("preset") or p.get("preset"), {})
                    track.sound = Sound.model_validate({**base, **preset_start, **patch, **p})
                except ValueError as error:
                    raise EditError(f"Those sound settings are out of range: {', '.join(sorted(set(p) - {'preset'}))}") from error
            elif action.kind == "character":
                keys(p, {"character", "intensity"})
                word = p.get("character")
                if not isinstance(word, str) or word.lower() not in character_module.CHARACTERS:
                    raise Unsupported(f"RDX has no sound character called '{word}'. It knows: {', '.join(sorted(character_module.CHARACTERS))}.")
                if track.role in {"drums", "audio"} and word.lower() in {"glide"}:
                    raise EditError("That character only applies to instrument parts")
                intensity = float(p.get("intensity", 0.6))
                changes = character_module.character_changes(track.sound, word.lower(), intensity)
                track.sound = Sound.model_validate({**track.sound.model_dump(), **changes})
            elif action.kind == "kit_sound":
                keys(p, set(Kit.model_fields) | {"machine"})
                if track.role != "drums":
                    raise EditError(f"{track.name} is not a drum track; drum voices only exist on one")
                machine: dict = {}
                if "machine" in p:
                    name = p["machine"]
                    if name not in design_module.DRUM_KITS:
                        raise Unsupported(f"There is no '{name}' drum machine. RDX knows: {', '.join(design_module.DRUM_KITS)}.")
                    machine = design_module.drum_settings(name)
                    if findings is not None:
                        findings.append(f"{track.name}: {name} — {design_module.DRUM_KITS[name].meaning}.")
                explicit = {k: v for k, v in p.items() if k != "machine"}
                base = Kit().model_dump() if machine else (track.kit or Kit()).model_dump()
                try:
                    track.kit = Kit.model_validate({**base, **machine, **explicit})
                except ValueError as error:
                    raise EditError(f"Those drum voice settings are out of range: {', '.join(sorted(explicit))}") from error
            elif action.kind == "sidechain":
                keys(p, {"source", "amount", "attack", "release", "curve", "trigger", "shape", "operation"})
                if p.get("operation") == "remove":
                    track.sidechain = None
                    continue
                settings: dict = {}
                if "shape" in p:
                    if p["shape"] not in sidechain_module.SHAPES:
                        raise Unsupported(f"There is no '{p['shape']}' ducking shape. Available: {', '.join(sidechain_module.SHAPES)}.")
                    shape = sidechain_module.SHAPES[p["shape"]]
                    settings = {"amount": shape.amount, "attack": shape.attack, "release": shape.release, "curve": shape.curve}
                elif track.sidechain:
                    settings = track.sidechain.model_dump()
                if "curve" in p and p["curve"] not in sidechain_module.CURVES:
                    raise Unsupported(f"There is no '{p['curve']}' ducking curve. Available: {', '.join(sidechain_module.CURVES)}.")
                if "trigger" in p and p["trigger"] not in sidechain_module.TRIGGERS:
                    raise Unsupported(f"Ducking cannot be triggered by '{p['trigger']}'. Available: {', '.join(sidechain_module.TRIGGERS)}.")
                source = default_source(project, p.get("source") or settings.get("source"), track)
                if source.id == track.id:
                    raise EditError(f"{track.name} cannot duck to itself; name the track that should trigger it")
                if source.role == "audio":
                    raise Unsupported(f"{source.name} is a recording, and RDX cannot pick hits out of audio. Duck to a drum or instrument part instead.")
                explicit = {k: v for k, v in p.items() if k in {"amount", "attack", "release", "curve", "trigger"}}
                try:
                    track.sidechain = Sidechain.model_validate({**settings, **explicit, "source": source.id})
                except ValueError as error:
                    raise EditError("Those ducking settings are out of range: depth is 0 to 1 and the release is up to 8 beats") from error
                if findings is not None:
                    findings.append(f"{track.name} ducks to {source.name}: " + sidechain_module.describe_settings(track.sidechain.amount, track.sidechain.release, track.sidechain.curve, track.sidechain.trigger) + ".")
            elif action.kind == "mix":
                keys(p, {"volume_db", "delta_db", "pan", "mute", "solo", "name"})
                changes = dict(p)
                if "delta_db" in changes:
                    changes["volume_db"] = max(-60.0, min(6.0, track.volume_db + float(changes.pop("delta_db"))))
                try:
                    checked = Track.model_validate({**track.model_dump(), **changes})
                except ValueError as error:
                    raise EditError(f"Those mixer settings are out of range: {', '.join(sorted(changes))}") from error
                for key in changes:
                    setattr(track, key, getattr(checked, key))
            else:
                sections = target_sections(project, action.section, selection)
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
                    elif action.kind == "kit":
                        keys(p, {"kit", "layers", "density", "crash", "fill", "roll", "roll_from_bar", "seed", "pickup"})
                        if track.role != "drums":
                            raise EditError(f"{track.name} is not a drum track; drum patterns need one")
                        name = p.get("kit")
                        if name is not None and name not in drums_module.KITS:
                            raise Unsupported(f"There is no '{name}' kit. Available: {', '.join(sorted(drums_module.KITS))}.")
                        layers = p.get("layers") or {}
                        if not isinstance(layers, dict) or any(not isinstance(v, str) for v in layers.values()):
                            raise EditError("Drum layers must be named patterns, for example {\"clap\": \"double\"}")
                        # Naming neither a kit nor its layers means "add this to
                        # what is already playing" — a crash on the drop, a fill
                        # into the next section. Regenerating from a default kit
                        # instead silently costs the section its pattern.
                        decorating = not name and not layers and clip is not None and clip.notes
                        if decorating:
                            if "density" in p:
                                raise EditError("Name a kit or the drum layers to change the density — I cannot rebuild a pattern without knowing what it is made of.")
                            notes = drums_module.decorate(list(clip.notes), section.bars, crash=bool(p.get("crash", False)), fill=bool(p.get("fill", False)), roll=bool(p.get("roll", False)), roll_from_bar=int(p["roll_from_bar"]) if "roll_from_bar" in p else None)
                            clip.notes = sorted(notes, key=lambda n: (n.start, n.pitch))
                            if findings is not None:
                                added = ", ".join(w for w, on in (("a crash", p.get("crash")), ("a fill", p.get("fill")), ("an accelerating roll", p.get("roll"))) if on)
                                findings.append(f"{section.name}: {added or 'nothing to add'}, over the pattern already there.")
                            continue
                        try:
                            notes = drums_module.build(section.bars, name, layers, density=float(p.get("density", 0.7)), seed=project.seed, crash=bool(p.get("crash", False)), fill=bool(p.get("fill", False)), pickup=bool(p.get("pickup", True)))
                        except KeyError as error:
                            raise Unsupported(f"There is no '{error.args[0]}' drum layer. Available: {', '.join(drums_module.LAYERS)}.") from error
                        except ValueError as error:
                            raise EditError(str(error)) from error
                        if p.get("roll"):
                            start_bar = int(p.get("roll_from_bar", max(0, section.bars - max(2, section.bars // 2))))
                            if not 0 <= start_bar < section.bars:
                                raise EditError("The roll starts outside this section")
                            notes = [n for n in notes if n.pitch != drums_module.SNARE or n.start < start_bar * 4] + drums_module.build_roll(section.bars, start_bar)
                        if findings is not None:
                            chosen = drums_module.resolve(name, layers)
                            findings.append(f"{section.name} kit: " + ", ".join(f"{layer} {pattern}" for layer, pattern in sorted(chosen.items()) if pattern != "none") + (", accelerating roll" if p.get("roll") else ""))
                        if not clip:
                            clip = Clip(name=track.name, section_id=section.id)
                            track.clips.append(clip)
                        clip.notes = sorted(notes, key=lambda n: (n.start, n.pitch))
                    elif action.kind == "harmony":
                        keys(p, {"from_track", "span", "voices", "low", "high", "velocity", "colour", "progression"})
                        if track.role in {"drums", "audio"}:
                            raise EditError("Chords need an instrument track")
                        wanted = p.get("progression")
                        source_track = source = None
                        if wanted is None:
                            source_track = target_tracks(project, p.get("from_track") or track.id, selection)[0]
                            source = next((c for c in source_track.clips if c.section_id == section.id), None)
                            if source is None or not source.notes:
                                raise EditError(f"{source_track.name} has nothing recorded in {section.name} to build chords from. Name a progression instead, for example \"i-VI-III-VII\" or one of: {', '.join(sorted(harmony_module.NAMED_PROGRESSIONS))}.")
                        span = float(p.get("span", 4))
                        if span not in {1, 2, 4, 8, 16}:
                            raise EditError("A chord can last 1, 2, 4, 8 or 16 beats")
                        voices = int(p.get("voices", 3))
                        if not 2 <= voices <= 5:
                            raise EditError("Chords use between two and five voices")
                        if wanted is not None:
                            try:
                                if wanted in harmony_module.NAMED_PROGRESSIONS:
                                    entries = harmony_module.named(wanted, section.bars, project.key, project.scale, span)
                                    heard = f"the {wanted} progression"
                                else:
                                    entries = harmony_module.from_degrees(harmony_module.parse_progression(wanted), section.bars, project.key, project.scale, span)
                                    heard = "the progression you named"
                            except ValueError as error:
                                raise EditError(str(error)) from error
                        else:
                            entries = harmony_module.progression(source.notes, section.bars, project.key, project.scale, span)
                            heard = ("chord roots" if harmony_module.looks_like_roots(source.notes, section.bars) else "a melody") + f" on {source_track.name}"
                        colour = p.get("colour")
                        if colour is not None:
                            if colour not in harmony_module.COLOURS:
                                raise Unsupported(f"There is no '{colour}' chord colour. Available: {', '.join(harmony_module.COLOURS)}.")
                            entries = harmony_module.colour_progression(entries, colour, project.scale)
                            if findings is not None and colour in harmony_module.BORROWS:
                                findings.append(harmony_module.BORROWS[colour])
                            # A seventh nobody hears is not a seventh: widen the
                            # voicing to carry the extension that was asked for.
                            if "voices" not in p:
                                voices = min(5, max(len(c.intervals) for _, _, c in entries))
                        if findings is not None:
                            findings.append(f"Took {heard} and built {harmony_module.describe(entries)} in {section.name}.")
                            # A progression written for one mode can land on a
                            # diminished chord in another. That is correct and
                            # it is also a surprise, so RDX says it rather than
                            # letting an unstable chord arrive unannounced.
                            odd = sorted({c.symbol for _, _, c in entries if c.triad == "diminished"})
                            if odd:
                                findings.append(f"{' and '.join(odd)} is diminished in {project.key} {project.scale} — that degree is unstable in this mode.")
                        low = int(p.get("low", 48))
                        high = int(p.get("high", 72))
                        if not 0 <= low < high <= 127:
                            raise EditError("The chord register is outside the playable range")
                        if not clip:
                            clip = Clip(name=track.name, section_id=section.id)
                            track.clips.append(clip)
                        clip.notes = harmony_module.voice(entries, low=low, high=high, voices=voices, velocity=int(p.get("velocity", 72)))
                    elif action.kind == "bassline":
                        keys(p, {"pattern", "progression", "from_track", "velocity", "low", "high"})
                        if track.role in {"drums", "audio"}:
                            raise EditError("A bassline needs an instrument track")
                        pattern = p.get("pattern", "offbeat")
                        if pattern not in bass_module.PATTERNS:
                            raise Unsupported(f"There is no '{pattern}' bass pattern. RDX knows: {', '.join(bass_module.PATTERNS)}.")
                        entries = progression_for(project, p, section, selection, "for the bass to follow")
                        try:
                            written = bass_module.line(pattern, entries, section.bars, low=int(p.get("low", 28)), high=int(p.get("high", 50)), velocity=int(p.get("velocity", 100)))
                        except (KeyError, ValueError) as error:
                            raise EditError(str(error)) from error
                        if not clip:
                            clip = Clip(name=track.name, section_id=section.id)
                            track.clips.append(clip)
                        clip.notes = written
                        if findings is not None:
                            findings.append(f"{track.name} in {section.name}: {bass_module.describe(pattern)}.")
                    elif action.kind == "melody":
                        keys(p, {"cell", "shape", "form", "progression", "from_track", "anchor", "density", "velocity", "low", "high"})
                        if track.role in {"drums", "audio"}:
                            raise EditError("A melody needs an instrument track")
                        cell, figure, form = p.get("cell", "pluck"), p.get("shape", "wave"), p.get("form", "trance")
                        anchor = str(p.get("anchor", "key"))
                        # Named things that do not exist are Unsupported, not a
                        # validation failure: the server sends these straight to
                        # the user instead of asking the model to try again,
                        # because rephrasing cannot conjure a shape nobody wrote.
                        for value, known, what in ((cell, motif_module.CELLS, "rhythm"), (figure, motif_module.SHAPES, "melodic shape"), (form, motif_module.FORMS, "phrase form"), (anchor, ("key", "chord"), "anchor")):
                            if value not in known:
                                raise Unsupported(f"There is no '{value}' {what}. RDX knows: {', '.join(known)}.")
                        entries = progression_for(project, p, section, selection, "for the melody to follow")
                        try:
                            written = motif_module.line(cell, figure, form, entries, section.bars, key=project.key, scale=project.scale, low=int(p.get("low", 60)), high=int(p.get("high", 88)), density=float(p.get("density", 1.0)), velocity=int(p.get("velocity", 92)), anchor=anchor)
                        except (KeyError, ValueError) as error:
                            raise EditError(str(error)) from error
                        if not clip:
                            clip = Clip(name=track.name, section_id=section.id)
                            track.clips.append(clip)
                        clip.notes = written
                        if findings is not None:
                            findings.append(f"{track.name} in {section.name}: {motif_module.describe(cell, figure, form)}.")
                    elif action.kind == "relate":
                        keys(p, {"operation", "from_track", "degrees", "grid", "density", "keep_rhythm", "octave", "against"})
                        if track.role in {"drums", "audio"}:
                            raise EditError("Relating one part to another is for instrument tracks")
                        operation = p.get("operation", "follow")
                        if operation not in parts_module.RELATIONS:
                            raise Unsupported(f"RDX cannot relate two parts by '{operation}'. It knows: {', '.join(parts_module.RELATIONS)}.")
                        other = target_tracks(project, p.get("from_track"), selection)[0]
                        if other.id == track.id:
                            raise EditError(f"{track.name} cannot be written against itself; name the other part")
                        source = next((c for c in other.clips if c.section_id == section.id), None)
                        if source is None or not source.notes:
                            raise EditError(f"{other.name} has nothing in {section.name} to work from")
                        length = section.bars * 4
                        existing = clip.notes if clip else []
                        try:
                            if operation == "follow":
                                written = parts_module.follow(source.notes, length, role=track.role, rhythm=existing if p.get("keep_rhythm", True) and existing else None)
                            elif operation == "counter":
                                # A whole kit leaves no gaps to answer; the kick
                                # does. So a drum source answers one voice.
                                against = p.get("against") or ("kick" if other.role == "drums" else None)
                                written = parts_module.counter(source.notes, length, role=track.role, grid=float(p.get("grid", 0.5)), density=float(p.get("density", 0.6)), key=project.key, scale=project.scale, seed=project.seed, against=against)
                            elif operation == "harmonise":
                                written = parts_module.harmonise(source.notes, degrees=int(p.get("degrees", 2)), key=project.key, scale=project.scale)
                            else:
                                written = parts_module.octaves(source.notes, direction=int(p.get("octave", -1)))
                        except ValueError as error:
                            raise EditError(str(error)) from error
                        written = [n for n in written if n.start < length]
                        for note in written:
                            note.duration = min(note.duration, length - note.start)
                        if not written:
                            raise EditError(f"Nothing could be written for {track.name} in {section.name}")
                        if not clip:
                            clip = Clip(name=track.name, section_id=section.id)
                            track.clips.append(clip)
                        clip.notes = sorted(written, key=lambda n: (n.start, n.pitch))
                        if findings is not None:
                            findings.append(f"{track.name} now " + parts_module.RELATIONS[operation].format(source=other.name) + f" in {section.name} ({len(clip.notes)} notes).")
                    elif action.kind == "automation":
                        keys(p, {"parameter", "points", "operation"})
                        if p.get("operation") == "remove":
                            track.automation = [a for a in track.automation if not (a.section_id == section.id and a.parameter == p.get("parameter"))]
                            continue
                        parameter = p.get("parameter")
                        if parameter not in AUTOMATION_RANGES:
                            raise Unsupported(f"RDX cannot draw a curve on '{parameter}'. It can automate: {', '.join(AUTOMATION_RANGES)}.")
                        try:
                            lane = Automation(section_id=section.id, **{k: v for k, v in p.items() if k != "operation"})
                        except ValueError as error:
                            low, high = AUTOMATION_RANGES[parameter]
                            raise EditError(f"That {parameter} curve does not fit: every value has to be between {low:g} and {high:g}, and the points have to move forwards in time.") from error
                        track.automation = [a for a in track.automation if not (a.section_id == section.id and a.parameter == lane.parameter)] + [lane]
                    elif action.kind == "notes" and not clip and p.get("operation", "replace") in {"replace", "add"}:
                        keys(p, {"notes", "operation"})
                        if track.role == "audio":
                            raise EditError("Record or import audio onto audio tracks")
                        track.clips.append(Clip(name=track.name, section_id=section.id, notes=[Note.model_validate(n) for n in p.get("notes", [])]))
                    elif not clip:
                        # Editing a whole track skips its empty sections; asking
                        # for one specific section that is empty is still an error.
                        if len(sections) > 1:
                            continue
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
                    elif action.kind == "phrase":
                        keys(p, {"operation", "amount", "shape", "degrees"})
                        if track.role == "drums":
                            raise EditError("Phrase shaping is for melodic parts; drums are shaped with kit and rhythm")
                        operation = p.get("operation", "shape")
                        length = section.bars * 4
                        before = len(clip.notes)
                        try:
                            if operation == "space":
                                clip.notes = melody_module.space(clip.notes, amount=float(p.get("amount", 0.4)), length=length)
                            elif operation == "fill":
                                clip.notes = melody_module.fill(clip.notes, amount=float(p.get("amount", 0.5)), key=project.key, scale=project.scale, length=length, seed=project.seed)
                            elif operation == "vary":
                                clip.notes = melody_module.vary(clip.notes, section.bars, key=project.key, scale=project.scale, amount=float(p.get("amount", 0.5)), seed=project.seed)
                            elif operation == "shape":
                                name = p.get("shape")
                                if name not in melody_module.CONTOURS:
                                    raise Unsupported(f"There is no '{name}' phrase shape. Available: {', '.join(melody_module.CONTOURS)}.")
                                degrees = p.get("degrees", 2)
                                if type(degrees) is not int:
                                    raise EditError("Reshaping moves a phrase by a whole number of scale degrees")
                                clip.notes = melody_module.shape(clip.notes, name, degrees=degrees, key=project.key, scale=project.scale, length=length)
                            else:
                                raise EditError("Unknown phrase operation. Use space, fill, vary or shape.")
                        except Unsupported:
                            raise
                        except ValueError as error:
                            raise EditError(str(error)) from error
                        clip.notes = [n for n in clip.notes if n.start < length]
                        for note in clip.notes:
                            note.duration = min(note.duration, length - note.start)
                        if findings is not None:
                            if operation == "shape":
                                findings.append(f"{track.name} in {section.name}: the phrase now {melody_module.CONTOURS[p.get('shape')].meaning}.")
                            else:
                                findings.append(f"{track.name} in {section.name}: {before} notes to {len(clip.notes)}.")
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
    return validated(project)


def context(project: Project, track_id: str | None, section_id: str | None, measured: dict | None = None) -> dict:
    """The compact picture of the project the model gets to reason over.

    It names the instrument on each track and how full the selected part is,
    because "make it warmer" means something different on a sub bass than on a
    string pad, and "add a melody" means something different to an empty clip.
    """
    selected = next((t for t in project.tracks if t.id == track_id), None)
    section = next((s for s in project.sections if s.id == section_id), None)
    clip = next((c for c in selected.clips if c.section_id == section_id), None) if selected and section else None
    detail: dict = {"track": track_id, "section": section_id}
    if selected:
        detail["instrument"] = selected.sound.preset
        detail["notes"] = len(clip.notes) if clip else 0
        active = {name: round(value, 3) for name, value in selected.sound.model_dump().items() if name in {"cutoff", "reverb", "flanger", "chorus", "autopan", "width", "drive"} and value}
        detail["sound"] = active
    if measured:
        # Only the names of the measured problems, not the numbers. The model
        # picks the operation; the module owns what the measurement means.
        problems = sorted({f.problem for f in mixdown_module.findings(mixdown_module.Mix.from_dict(measured), project)})
        detail["mix_measured"] = problems or ["nothing"]
    return {"tempo": project.tempo, "key": project.key, "scale": project.scale,
            "tracks": [{"id": t.id, "name": t.name, "role": t.role, "instrument": t.sound.preset, "locked": t.locked, "volume_db": t.volume_db, **({"ducks_to": t.sidechain.source} if t.sidechain else {})} for t in project.tracks],
            "sections": [{"id": s.id, "name": s.name, "bars": s.bars, "energy": s.energy} for s in project.sections],
            "selected": detail}
